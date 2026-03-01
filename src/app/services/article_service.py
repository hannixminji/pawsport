import logging
from dataclasses import dataclass

from sqlalchemy import any_, delete, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.enums import ActorType
from ..core.exceptions.authorization_exceptions import ForbiddenError
from ..core.exceptions.db_exceptions import NonTransientDatabaseError, TransientDatabaseError
from ..core.exceptions.domain_exceptions import InvalidInputError, NotFoundError
from ..core.schemas import Actor, PaginatedResponse
from ..core.search_engine.engine import SearchEngine
from ..core.search_engine.enums import FilterOp
from ..core.search_engine.schemas import SearchRequest
from ..core.utils.pagination import compute_offset
from ..core.utils.update import apply_partial_update
from ..models.article import Article
from ..schemas.article import ArticleCreate, ArticleRead, ArticleUpdate

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ArticleService:
    db: AsyncSession

    ADMIN_SEARCH_BLACKLIST_COLUMNS = frozenset({
        "id",
        "content",
        "summary",
        "tags",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ALLOWED_FILTER_OPERATORS_BY_COLUMN = {
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
    SEARCH_SORTABLE_COLUMNS = {
        "title",
        "created_at",
    }

    def _is_unique_constraint_violation(self, error: IntegrityError, constraint_name: str) -> bool:
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

            if self._is_unique_constraint_violation(error, "uq_article_title_active"):
                raise InvalidInputError("An article with this title already exists.")

            raise InvalidInputError("Unable to create the article.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to create the article. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to create the article."
            ) from error

        await self.db.refresh(article_model)
        return ArticleRead.model_validate(article_model)

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
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to perform this action.")

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
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to perform this action.")

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

        apply_partial_update(target=db_article, input=article_input)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_article_title_active"):
                raise InvalidInputError("An article with this title already exists.")

            raise InvalidInputError("Unable to update the article.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update the article. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update the article."
            ) from error

    async def soft_delete(
        self,
        *,
        actor: Actor,
        article_id: int,
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to delete an article.")

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

            raise TransientDatabaseError(
                "Failed to delete the article. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete the article."
            ) from error

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

            raise TransientDatabaseError(
                "Failed to delete articles. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete articles."
            ) from error

    async def hard_delete(
        self,
        *,
        actor: Actor,
        article_id: int,
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to permanently delete an article.")

        statement = (
            delete(Article)
            .where(Article.id == article_id)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete the article. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete the article."
            ) from error

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

        statement = (
            delete(Article)
            .where(Article.id == any_(list(article_ids)))
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete articles. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete articles."
            ) from error
