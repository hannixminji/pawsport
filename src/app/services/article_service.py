import logging
from dataclasses import dataclass, field
from typing import ClassVar

from sqlalchemy import any_, delete, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.audit.protocol import AuditLogger
from ..core.enums import ActionStatus, ActorType
from ..core.exceptions.authorization_exceptions import ForbiddenError
from ..core.exceptions.db_exceptions import NonTransientDatabaseError, TransientDatabaseError
from ..core.exceptions.domain_exceptions import InvalidInputError, NotFoundError
from ..core.schemas import Actor, PaginatedResponse
from ..core.search_engine.engine import SearchEngine
from ..core.search_engine.enums import FilterOp
from ..core.search_engine.schemas import SearchRequest
from ..core.utils.diff import extract_changed_fields
from ..core.utils.pagination import compute_offset
from ..core.utils.update import apply_partial_update
from ..models.article import Article
from ..schemas.article import ArticleCreate, ArticleRead, ArticleUpdate

LOGGER = logging.getLogger(__name__)

_RESOURCE_TYPE = "article"


@dataclass(slots=True)
class ArticleService:
    db: AsyncSession
    audit_logger: AuditLogger | None = field(default=None)

    ADMIN_SEARCH_BLACKLIST_COLUMNS: ClassVar[frozenset[str]] = frozenset({
        "id",
        "content",
        "summary",
        "tags",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ALLOWED_FILTER_OPERATORS_BY_COLUMN: ClassVar[dict] = {
        "title": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
        }),
        "category": frozenset({
            FilterOp.EQ,
            FilterOp.IN,
        }),
        "created_at": frozenset({
            FilterOp.LT,
            FilterOp.LTE,
            FilterOp.GT,
            FilterOp.GTE,
        }),
    }
    SEARCH_SORTABLE_COLUMNS: ClassVar[set[str]] = {
        "title",
        "created_at",
    }

    @staticmethod
    def _is_unique_constraint_violation(error: IntegrityError, constraint_name: str) -> bool:
        original_exception = getattr(error, "orig", None)
        if original_exception is None:
            return False

        return constraint_name in str(original_exception)

    async def _get_article_by_id(self, article_id: int) -> Article | None:
        return (
            await self.db.execute(
                select(Article)
                .where(
                    Article.id == article_id,
                    Article.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

    async def create(
        self,
        *,
        actor: Actor,
        article_input: ArticleCreate,
    ) -> ArticleRead:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to create an article.")

        article_model = Article(**article_input.model_dump())
        self.db.add(article_model)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self.audit_logger:
                await self.audit_logger.log(
                    actor=actor,
                    action="article.create",
                    status=ActionStatus.FAILURE,
                    resource_type=_RESOURCE_TYPE,
                    error_code="DUPLICATE_TITLE",
                    error_message=str(error),
                    extra_metadata={"title": article_input.title, "category": article_input.category},
                )

            if self._is_unique_constraint_violation(error, "uq_article_title_active"):
                raise InvalidInputError("An article with this title already exists.")

            raise InvalidInputError("Unable to create the article.")

        except OperationalError as error:
            await self.db.rollback()

            if self.audit_logger:
                await self.audit_logger.log(
                    actor=actor,
                    action="article.create",
                    status=ActionStatus.FAILURE,
                    resource_type=_RESOURCE_TYPE,
                    error_code="TRANSIENT_DB_ERROR",
                    error_message=str(error),
                    extra_metadata={"title": article_input.title, "category": article_input.category},
                )

            raise TransientDatabaseError(
                "Failed to create the article. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            if self.audit_logger:
                await self.audit_logger.log(
                    actor=actor,
                    action="article.create",
                    status=ActionStatus.FAILURE,
                    resource_type=_RESOURCE_TYPE,
                    error_code="DB_ERROR",
                    error_message=str(error),
                    extra_metadata={"title": article_input.title, "category": article_input.category},
                )

            raise NonTransientDatabaseError(
                "Failed to create the article."
            ) from error

        await self.db.refresh(article_model)

        article_read = ArticleRead.model_validate(article_model)

        if self.audit_logger:
            await self.audit_logger.log(
                actor=actor,
                action="article.create",
                status=ActionStatus.SUCCESS,
                resource_type=_RESOURCE_TYPE,
                resource_id=article_model.id,
                after_state=article_read.model_dump(mode="json"),
                extra_metadata={"title": article_model.title, "category": article_model.category},
            )

        return article_read

    async def search(
        self,
        *,
        actor: Actor,
        search_request: SearchRequest,
    ) -> PaginatedResponse[ArticleRead]:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to perform this search.")

        engine = SearchEngine(
            db=self.db,
            model=Article,
            blacklisted_columns=self.ADMIN_SEARCH_BLACKLIST_COLUMNS,
            allowed_ops=self.ALLOWED_FILTER_OPERATORS_BY_COLUMN,
            column_order_map=None,
            sortable_columns=self.SEARCH_SORTABLE_COLUMNS,
            max_in_list_size=100,
            max_depth=1,
        )

        base_query = (
            select(Article)
            .where(Article.is_deleted.is_(False))
        )
        result = await engine.search(
            base_query=base_query,
            values=search_request,
            serializer=ArticleRead.model_validate,
        )

        return PaginatedResponse[ArticleRead](
            data=result.data,
            total_count=result.total_count,
            has_more=(result.page * result.items_per_page) < result.total_count,
            page=result.page,
            items_per_page=result.items_per_page,
        )

    async def get_all_articles(
        self,
        *,
        actor: Actor,
        page: int,
        items_per_page: int,
    ) -> PaginatedResponse[ArticleRead]:
        db_articles = (
            await self.db.execute(
                select(Article)
                .where(Article.is_deleted.is_(False))
                .offset(compute_offset(page, items_per_page))
                .limit(items_per_page)
            )
        ).scalars().all()

        total_count = (
            await self.db.execute(
                select(func.count())
                .select_from(Article)
                .where(Article.is_deleted.is_(False))
            )
        ).scalar_one()

        return PaginatedResponse[ArticleRead](
            data=[ArticleRead.model_validate(article) for article in db_articles],
            total_count=total_count,
            has_more=(page * items_per_page) < total_count,
            page=page,
            items_per_page=items_per_page,
        )

    async def get_article(
        self,
        *,
        actor: Actor,
        article_id: int,
    ) -> ArticleRead:
        db_article = await self._get_article_by_id(article_id)
        if db_article is None:
            raise NotFoundError("Article not found.")

        return ArticleRead.model_validate(db_article)

    async def update(
        self,
        *,
        actor: Actor,
        article_id: int,
        article_input: ArticleUpdate,
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to update an article.")

        db_article = await self._get_article_by_id(article_id)
        if db_article is None:
            raise NotFoundError("Article not found.")

        before_snapshot = ArticleRead.model_validate(db_article).model_dump(mode="json")

        apply_partial_update(target=db_article, input=article_input)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self.audit_logger:
                await self.audit_logger.log(
                    actor=actor,
                    action="article.update",
                    status=ActionStatus.FAILURE,
                    resource_type=_RESOURCE_TYPE,
                    resource_id=article_id,
                    error_code="DUPLICATE_TITLE",
                    error_message=str(error),
                    extra_metadata={"title": article_input.title, "category": article_input.category},
                )

            if self._is_unique_constraint_violation(error, "uq_article_title_active"):
                raise InvalidInputError("An article with this title already exists.")

            raise InvalidInputError("Unable to update the article.")

        except OperationalError as error:
            await self.db.rollback()

            if self.audit_logger:
                await self.audit_logger.log(
                    actor=actor,
                    action="article.update",
                    status=ActionStatus.FAILURE,
                    resource_type=_RESOURCE_TYPE,
                    resource_id=article_id,
                    error_code="TRANSIENT_DB_ERROR",
                    error_message=str(error),
                    extra_metadata={"title": article_input.title, "category": article_input.category},
                )

            raise TransientDatabaseError(
                "Failed to update the article. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            if self.audit_logger:
                await self.audit_logger.log(
                    actor=actor,
                    action="article.update",
                    status=ActionStatus.FAILURE,
                    resource_type=_RESOURCE_TYPE,
                    resource_id=article_id,
                    error_code="DB_ERROR",
                    error_message=str(error),
                    extra_metadata={"title": article_input.title, "category": article_input.category},
                )

            raise NonTransientDatabaseError(
                "Failed to update the article."
            ) from error

        await self.db.refresh(db_article)

        after_snapshot = ArticleRead.model_validate(db_article).model_dump(mode="json")
        before_state, after_state = extract_changed_fields(before_snapshot, after_snapshot)

        if self.audit_logger:
            await self.audit_logger.log(
                actor=actor,
                action="article.update",
                status=ActionStatus.SUCCESS,
                resource_type=_RESOURCE_TYPE,
                resource_id=article_id,
                before_state=before_state,
                after_state=after_state,
                extra_metadata={"title": db_article.title, "category": db_article.category},
            )

    async def soft_delete(
        self,
        *,
        actor: Actor,
        article_id: int,
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to delete an article.")

        db_article = await self._get_article_by_id(article_id)

        statement = (
            update(Article)
            .where(
                Article.id == article_id,
                Article.is_deleted.is_(False),
            )
            .values(
                deleted_at=func.now(),
                is_deleted=True,
            )
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            if self.audit_logger:
                await self.audit_logger.log(
                    actor=actor,
                    action="article.soft_delete",
                    status=ActionStatus.FAILURE,
                    resource_type=_RESOURCE_TYPE,
                    resource_id=article_id,
                    error_code="TRANSIENT_DB_ERROR",
                    error_message=str(error),
                    extra_metadata={"title": db_article.title if db_article else None},
                )

            raise TransientDatabaseError(
                "Failed to delete the article. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            if self.audit_logger:
                await self.audit_logger.log(
                    actor=actor,
                    action="article.soft_delete",
                    status=ActionStatus.FAILURE,
                    resource_type=_RESOURCE_TYPE,
                    resource_id=article_id,
                    error_code="DB_ERROR",
                    error_message=str(error),
                    extra_metadata={"title": db_article.title if db_article else None},
                )

            raise NonTransientDatabaseError(
                "Failed to delete the article."
            ) from error

        if self.audit_logger:
            await self.audit_logger.log(
                actor=actor,
                action="article.soft_delete",
                status=ActionStatus.SUCCESS,
                resource_type=_RESOURCE_TYPE,
                resource_id=article_id,
                extra_metadata={"title": db_article.title if db_article else None},
            )

    async def bulk_soft_delete(
        self,
        *,
        actor: Actor,
        article_ids: set[int],
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to delete articles.")

        if not article_ids:
            return

        sorted_article_ids = sorted(article_ids)

        statement = (
            update(Article)
            .where(
                Article.id == any_(list(article_ids)),
                Article.is_deleted.is_(False),
            )
            .values(
                deleted_at=func.now(),
                is_deleted=True,
            )
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            if self.audit_logger:
                await self.audit_logger.log(
                    actor=actor,
                    action="article.bulk_soft_delete",
                    status=ActionStatus.FAILURE,
                    resource_type=_RESOURCE_TYPE,
                    error_code="TRANSIENT_DB_ERROR",
                    error_message=str(error),
                    extra_metadata={"article_ids": sorted_article_ids, "count": len(sorted_article_ids)},
                )

            raise TransientDatabaseError(
                "Failed to delete articles. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            if self.audit_logger:
                await self.audit_logger.log(
                    actor=actor,
                    action="article.bulk_soft_delete",
                    status=ActionStatus.FAILURE,
                    resource_type=_RESOURCE_TYPE,
                    error_code="DB_ERROR",
                    error_message=str(error),
                    extra_metadata={"article_ids": sorted_article_ids, "count": len(sorted_article_ids)},
                )

            raise NonTransientDatabaseError(
                "Failed to delete articles."
            ) from error

        if self.audit_logger:
            await self.audit_logger.log(
                actor=actor,
                action="article.bulk_soft_delete",
                status=ActionStatus.SUCCESS,
                resource_type=_RESOURCE_TYPE,
                extra_metadata={"article_ids": sorted_article_ids, "count": len(sorted_article_ids)},
            )

    async def hard_delete(
        self,
        *,
        actor: Actor,
        article_id: int,
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to permanently delete an article.")

        db_article = await self._get_article_by_id(article_id)

        statement = (
            delete(Article)
            .where(Article.id == article_id)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            if self.audit_logger:
                await self.audit_logger.log(
                    actor=actor,
                    action="article.hard_delete",
                    status=ActionStatus.FAILURE,
                    resource_type=_RESOURCE_TYPE,
                    resource_id=article_id,
                    error_code="TRANSIENT_DB_ERROR",
                    error_message=str(error),
                    extra_metadata={"title": db_article.title if db_article else None},
                )

            raise TransientDatabaseError(
                "Failed to permanently delete the article. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            if self.audit_logger:
                await self.audit_logger.log(
                    actor=actor,
                    action="article.hard_delete",
                    status=ActionStatus.FAILURE,
                    resource_type=_RESOURCE_TYPE,
                    resource_id=article_id,
                    error_code="DB_ERROR",
                    error_message=str(error),
                    extra_metadata={"title": db_article.title if db_article else None},
                )

            raise NonTransientDatabaseError(
                "Failed to permanently delete the article."
            ) from error

        if self.audit_logger:
            await self.audit_logger.log(
                actor=actor,
                action="article.hard_delete",
                status=ActionStatus.SUCCESS,
                resource_type=_RESOURCE_TYPE,
                resource_id=article_id,
                extra_metadata={"title": db_article.title if db_article else None},
            )

    async def bulk_hard_delete(
        self,
        *,
        actor: Actor,
        article_ids: set[int],
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to permanently delete articles.")

        if not article_ids:
            return

        sorted_article_ids = sorted(article_ids)

        statement = (
            delete(Article)
            .where(Article.id == any_(list(article_ids)))
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            if self.audit_logger:
                await self.audit_logger.log(
                    actor=actor,
                    action="article.bulk_hard_delete",
                    status=ActionStatus.FAILURE,
                    resource_type=_RESOURCE_TYPE,
                    error_code="TRANSIENT_DB_ERROR",
                    error_message=str(error),
                    extra_metadata={"article_ids": sorted_article_ids, "count": len(sorted_article_ids)},
                )

            raise TransientDatabaseError(
                "Failed to permanently delete articles. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            if self.audit_logger:
                await self.audit_logger.log(
                    actor=actor,
                    action="article.bulk_hard_delete",
                    status=ActionStatus.FAILURE,
                    resource_type=_RESOURCE_TYPE,
                    error_code="DB_ERROR",
                    error_message=str(error),
                    extra_metadata={"article_ids": sorted_article_ids, "count": len(sorted_article_ids)},
                )

            raise NonTransientDatabaseError(
                "Failed to permanently delete articles."
            ) from error

        if self.audit_logger:
            await self.audit_logger.log(
                actor=actor,
                action="article.bulk_hard_delete",
                status=ActionStatus.SUCCESS,
                resource_type=_RESOURCE_TYPE,
                extra_metadata={"article_ids": sorted_article_ids, "count": len(sorted_article_ids)},
            )
