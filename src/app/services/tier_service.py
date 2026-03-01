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
from ..models.tier import Tier
from ..schemas.tier import TierCreate, TierRead, TierUpdate

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class TierService:
    db: AsyncSession

    ADMIN_SEARCH_BLACKLIST_COLUMNS = frozenset({
        "id",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ALLOWED_FILTER_OPERATORS_BY_COLUMN = {
        "name": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
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
        "name",
        "created_at",
    }

    def _is_unique_constraint_violation(self, error: IntegrityError, constraint_name: str) -> bool:
        original_exception = getattr(error, "orig", None)
        if original_exception is None:
            return False

        return constraint_name in str(original_exception)

    async def _get_tier_by_id(self, tier_id: int) -> Tier | None:
        return (
            await self.db.execute(
                select(Tier)
                .where(
                    Tier.id == tier_id,
                    Tier.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

    async def create(
        self,
        *,
        actor: Actor,
        tier_input: TierCreate,
    ) -> TierRead:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to create a tier.")

        tier_model = Tier(**tier_input.model_dump())
        self.db.add(tier_model)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_tier_name"):
                raise InvalidInputError("A tier with this name already exists.")

            raise InvalidInputError("Unable to create the tier.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to create the tier. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to create the tier."
            ) from error

        await self.db.refresh(tier_model)
        return TierRead.model_validate(tier_model)

    async def search(
        self,
        *,
        actor: Actor,
        search_request: SearchRequest,
    ) -> PaginatedResponse[TierRead]:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to perform this search.")

        engine = SearchEngine(
            db=self.db,
            model=Tier,
            blacklisted_columns=self.ADMIN_SEARCH_BLACKLIST_COLUMNS,
            allowed_ops=self.ALLOWED_FILTER_OPERATORS_BY_COLUMN,
            column_order_map=None,
            sortable_columns=self.SEARCH_SORTABLE_COLUMNS,
            max_in_list_size=100,
            max_depth=1,
        )

        base_query = (
            select(Tier)
            .where(Tier.is_deleted.is_(False))
        )
        result = await engine.search(
            base_query=base_query,
            values=search_request,
            serializer=TierRead.model_validate,
        )

        return PaginatedResponse[TierRead](
            data=result.data,
            total_count=result.total_count,
            has_more=(result.page * result.items_per_page) < result.total_count,
            page=result.page,
            items_per_page=result.items_per_page,
        )

    async def get_all_tiers(
        self,
        *,
        actor: Actor,
        page: int,
        items_per_page: int,
    ) -> PaginatedResponse[TierRead]:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to perform this action.")

        db_tiers = (
            await self.db.execute(
                select(Tier)
                .where(Tier.is_deleted.is_(False))
                .offset(compute_offset(page, items_per_page))
                .limit(items_per_page)
            )
        ).scalars().all()

        total_count = (
            await self.db.execute(
                select(func.count())
                .select_from(Tier)
                .where(Tier.is_deleted.is_(False))
            )
        ).scalar_one()

        return PaginatedResponse[TierRead](
            data=[TierRead.model_validate(tier) for tier in db_tiers],
            total_count=total_count,
            has_more=(page * items_per_page) < total_count,
            page=page,
            items_per_page=items_per_page,
        )

    async def get_tier(
        self,
        *,
        actor: Actor,
        tier_id: int,
    ) -> TierRead:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to perform this action.")

        db_tier = await self._get_tier_by_id(tier_id)
        if db_tier is None:
            raise NotFoundError("Tier not found.")

        return TierRead.model_validate(db_tier)

    async def update(
        self,
        *,
        actor: Actor,
        tier_id: int,
        tier_input: TierUpdate,
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to update a tier.")

        db_tier = await self._get_tier_by_id(tier_id)
        if db_tier is None:
            raise NotFoundError("Tier not found.")

        apply_partial_update(target=db_tier, input=tier_input)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_tier_name"):
                raise InvalidInputError("A tier with this name already exists.")

            raise InvalidInputError("Unable to update the tier.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update the tier. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update the tier."
            ) from error

    async def soft_delete(
        self,
        *,
        actor: Actor,
        tier_id: int,
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to delete a tier.")

        statement = (
            update(Tier)
            .where(
                Tier.id == tier_id,
                Tier.is_deleted.is_(False),
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
                "Failed to delete the tier. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete the tier."
            ) from error

    async def bulk_soft_delete(
        self,
        *,
        actor: Actor,
        tier_ids: set[int],
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to delete tiers in bulk.")

        if not tier_ids:
            return

        statement = (
            update(Tier)
            .where(
                Tier.id == any_(list(tier_ids)),
                Tier.is_deleted.is_(False),
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
                "Failed to delete tiers. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete tiers."
            ) from error

    async def hard_delete(
        self,
        *,
        actor: Actor,
        tier_id: int,
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to permanently delete a tier.")

        statement = (
            delete(Tier)
            .where(Tier.id == tier_id)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()
            raise InvalidInputError(
                "Unable to delete the tier because it is referenced by other records."
            ) from error

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete the tier. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete the tier."
            ) from error

    async def bulk_hard_delete(
        self,
        *,
        actor: Actor,
        tier_ids: set[int],
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to permanently delete tiers.")

        if not tier_ids:
            return

        statement = (
            delete(Tier)
            .where(Tier.id == any_(list(tier_ids)))
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()
            raise InvalidInputError(
                "Unable to delete one or more tiers because they are referenced by other records."
            ) from error

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete tiers. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete tiers."
            ) from error
