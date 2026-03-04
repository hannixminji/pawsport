import logging
from dataclasses import dataclass
from typing import ClassVar

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
from ..models.rate_limit import RateLimit
from ..models.tier import Tier
from ..schemas.rate_limit import RateLimitCreate, RateLimitRead, RateLimitUpdate

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class RateLimitService:
    db: AsyncSession

    ADMIN_SEARCH_BLACKLIST_COLUMNS: ClassVar[frozenset[str]] = frozenset({
        "id",
        "tier_id",
        "limit",
        "period",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ALLOWED_FILTER_OPERATORS_BY_COLUMN: ClassVar[dict] = {
        "tier_id": frozenset({
            FilterOp.EQ,
        }),
        "name": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
        }),
        "path": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
        }),
        "created_at": frozenset({
            FilterOp.LT,
            FilterOp.LTE,
            FilterOp.GT,
            FilterOp.GTE,
        }),
    }
    SEARCH_SORTABLE_COLUMNS: ClassVar[set[str]] = {
        "name",
        "path",
        "created_at",
    }

    @staticmethod
    def _is_unique_constraint_violation(error: IntegrityError, constraint_name: str) -> bool:
        original_exception = getattr(error, "orig", None)
        if original_exception is None:
            return False

        return constraint_name in str(original_exception)

    async def _get_rate_limit(self, rate_limit_id: int, tier_id: int) -> RateLimit | None:
        return (
            await self.db.execute(
                select(RateLimit)
                .where(
                    RateLimit.id == rate_limit_id,
                    RateLimit.tier_id == tier_id,
                    RateLimit.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

    async def _get_rate_limit_by_id(self, rate_limit_id: int) -> RateLimit | None:
        return (
            await self.db.execute(
                select(RateLimit)
                .where(
                    RateLimit.id == rate_limit_id,
                    RateLimit.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

    async def _get_tier_id_by_name(self, tier_name: str) -> int | None:
        return (
            await self.db.execute(
                select(Tier.id)
                .where(Tier.name == tier_name)
            )
        ).scalar_one_or_none()

    async def create(
        self,
        *,
        actor: Actor,
        tier_name: str,
        rate_limit_input: RateLimitCreate,
    ) -> RateLimitRead:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to create a rate limit.")

        tier_id = await self._get_tier_id_by_name(tier_name)
        if tier_id is None:
            raise NotFoundError("Tier not found.")

        rate_limit_model = RateLimit(tier_id=tier_id, **rate_limit_input.model_dump())
        self.db.add(rate_limit_model)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_rate_limit_tier_id_name"):
                raise InvalidInputError("A rate limit with this name already exists for this tier.")

            if self._is_unique_constraint_violation(error, "uq_rate_limit_tier_id_path"):
                raise InvalidInputError("A rate limit for this path already exists for this tier.")

            raise InvalidInputError("Unable to create the rate limit.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to create the rate limit. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to create the rate limit."
            ) from error

        await self.db.refresh(rate_limit_model)
        return RateLimitRead.model_validate(rate_limit_model)

    async def search(
        self,
        *,
        actor: Actor,
        search_request: SearchRequest,
        tier_name: str | None = None,
    ) -> PaginatedResponse[RateLimitRead]:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to search rate limits.")

        engine = SearchEngine(
            db=self.db,
            model=RateLimit,
            blacklisted_columns=self.ADMIN_SEARCH_BLACKLIST_COLUMNS,
            allowed_ops=self.ALLOWED_FILTER_OPERATORS_BY_COLUMN,
            column_order_map=None,
            sortable_columns=self.SEARCH_SORTABLE_COLUMNS,
            max_in_list_size=100,
            max_depth=1,
        )

        base_query = (
            select(RateLimit)
            .where(RateLimit.is_deleted.is_(False))
        )

        if tier_name is not None:
            tier_id = await self._get_tier_id_by_name(tier_name)
            if tier_id is None:
                raise NotFoundError("Tier not found.")

            base_query = base_query.where(RateLimit.tier_id == tier_id)

        result = await engine.search(
            base_query=base_query,
            values=search_request,
            serializer=RateLimitRead.model_validate,
        )

        return PaginatedResponse[RateLimitRead](
            data=result.data,
            total_count=result.total_count,
            has_more=(result.page * result.items_per_page) < result.total_count,
            page=result.page,
            items_per_page=result.items_per_page,
        )

    async def get_rate_limits(
        self,
        *,
        actor: Actor,
        page: int,
        items_per_page: int,
        tier_name: str | None = None,
    ) -> PaginatedResponse[RateLimitRead]:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to view rate limits.")

        base_query = (
            select(RateLimit)
            .where(RateLimit.is_deleted.is_(False))
        )

        if tier_name is not None:
            tier_id = await self._get_tier_id_by_name(tier_name)
            if tier_id is None:
                raise NotFoundError("Tier not found.")

            base_query = base_query.where(RateLimit.tier_id == tier_id)

        db_rate_limits = (
            await self.db.execute(
                base_query
                .order_by(RateLimit.created_at.desc())
                .offset(compute_offset(page, items_per_page))
                .limit(items_per_page)
            )
        ).scalars().all()

        total_count = (
            await self.db.execute(
                select(func.count())
                .select_from(base_query.subquery())
            )
        ).scalar_one()

        return PaginatedResponse[RateLimitRead](
            data=[RateLimitRead.model_validate(rate_limit) for rate_limit in db_rate_limits],
            total_count=total_count,
            has_more=(page * items_per_page) < total_count,
            page=page,
            items_per_page=items_per_page,
        )

    async def get_rate_limit(
        self,
        *,
        actor: Actor,
        rate_limit_id: int,
    ) -> RateLimitRead:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to view this rate limit.")

        db_rate_limit = await self._get_rate_limit_by_id(rate_limit_id)
        if db_rate_limit is None:
            raise NotFoundError("Rate limit not found.")

        return RateLimitRead.model_validate(db_rate_limit)

    async def update(
        self,
        *,
        actor: Actor,
        rate_limit_id: int,
        rate_limit_input: RateLimitUpdate,
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to update a rate limit.")

        db_rate_limit = await self._get_rate_limit(rate_limit_id)
        if db_rate_limit is None:
            raise NotFoundError("Rate limit not found.")

        apply_partial_update(target=db_rate_limit, input=rate_limit_input)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_rate_limit_tier_id_name"):
                raise InvalidInputError("A rate limit with this name already exists for this tier.")

            if self._is_unique_constraint_violation(error, "uq_rate_limit_tier_id_path"):
                raise InvalidInputError("A rate limit for this path already exists for this tier.")

            raise InvalidInputError("Unable to update the rate limit.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update the rate limit. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update the rate limit."
            ) from error

    async def soft_delete(
        self,
        *,
        actor: Actor,
        rate_limit_id: int,
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to delete a rate limit.")

        statement = (
            update(RateLimit)
            .where(
                RateLimit.id == rate_limit_id,
                RateLimit.is_deleted.is_(False),
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
                "Failed to delete the rate limit. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete the rate limit."
            ) from error

    async def bulk_soft_delete(
        self,
        *,
        actor: Actor,
        rate_limit_ids: set[int],
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to delete rate limits in bulk.")

        if not rate_limit_ids:
            return

        statement = (
            update(RateLimit)
            .where(
                RateLimit.id == any_(list(rate_limit_ids)),
                RateLimit.is_deleted.is_(False),
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
                "Failed to delete rate limits. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete rate limits."
            ) from error

    async def hard_delete(
        self,
        *,
        actor: Actor,
        rate_limit_id: int,
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to permanently delete a rate limit.")

        statement = (
            delete(RateLimit)
            .where(RateLimit.id == rate_limit_id)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete the rate limit. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete the rate limit."
            ) from error

    async def bulk_hard_delete(
        self,
        *,
        actor: Actor,
        rate_limit_ids: set[int],
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to permanently delete rate limits.")

        if not rate_limit_ids:
            return

        statement = (
            delete(RateLimit)
            .where(RateLimit.id == any_(list(rate_limit_ids)))
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete rate limits. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete rate limits."
            ) from error
