import logging
from dataclasses import dataclass
from typing import ClassVar

from sqlalchemy import any_, delete, func, select, update
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.enums import ActorType
from ..core.exceptions.authorization_exceptions import ForbiddenError
from ..core.exceptions.db_exceptions import NonTransientDatabaseError, TransientDatabaseError
from ..core.exceptions.domain_exceptions import NotFoundError
from ..core.schemas import Actor, PaginatedResponse
from ..core.search_engine.engine import SearchEngine
from ..core.search_engine.enums import FilterOp
from ..core.search_engine.schemas import SearchRequest
from ..core.utils.pagination import compute_offset
from ..core.utils.update import apply_partial_update
from ..models.pet import Pet
from ..models.pet_schedule import PetSchedule
from ..schemas.pet_schedule import (
    PetScheduleCreate,
    PetScheduleRead,
    PetScheduleUpdate,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PetScheduleService:
    db: AsyncSession

    MOBILE_SEARCH_BLACKLIST_COLUMNS: ClassVar[frozenset[str]] = frozenset({
        "id",
        "pet_id",
        "recurrence_rule",
        "description",
        "is_recurring",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ADMIN_SEARCH_BLACKLIST_COLUMNS: ClassVar[frozenset[str]] = frozenset({
        "id",
        "recurrence_rule",
        "description",
        "is_recurring",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ALLOWED_FILTER_OPERATORS_BY_COLUMN: ClassVar[dict] = {
        "pet_id": frozenset({
            FilterOp.EQ,
        }),
        "title": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
        }),
        "schedule_type": frozenset({
            FilterOp.EQ,
            FilterOp.IN,
        }),
        "scheduled_at": frozenset({
            FilterOp.LT,
            FilterOp.LTE,
            FilterOp.GT,
            FilterOp.GTE,
        }),
        "next_schedule_at": frozenset({
            FilterOp.LT,
            FilterOp.LTE,
            FilterOp.GT,
            FilterOp.GTE,
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
        "scheduled_at",
        "next_schedule_at",
        "created_at",
    }

    async def _get_owned_pet_owner_id(self, actor: Actor, pet_id: int) -> int | None:
        return (
            await self.db.execute(
                select(Pet.owner_id)
                .where(
                    Pet.id == pet_id,
                    Pet.owner_id == actor.id,
                    Pet.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

    async def _require_pet_ownership(self, actor: Actor, pet_id: int) -> None:
        owner_id = await self._get_owned_pet_owner_id(actor, pet_id)
        if owner_id is None:
            raise NotFoundError("Pet not found.")

    async def _require_pet_access(self, actor: Actor, pet_id: int) -> None:
        if actor.actor_type not in (ActorType.ADMIN_USER, ActorType.MOBILE_USER):
            raise ForbiddenError("You do not have permission to access this pet.")

        if actor.actor_type == ActorType.MOBILE_USER:
            await self._require_pet_ownership(actor, pet_id)

    async def _get_owned_schedule_id(self, actor: Actor, schedule_id: int) -> int | None:
        return (
            await self.db.execute(
                select(PetSchedule.id)
                .join(Pet, Pet.id == PetSchedule.pet_id)
                .where(
                    Pet.owner_id == actor.id,
                    Pet.is_deleted.is_(False),
                    PetSchedule.id == schedule_id,
                    PetSchedule.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

    async def _require_schedule_ownership(self, actor: Actor, schedule_id: int) -> None:
        result = await self._get_owned_schedule_id(actor, schedule_id)
        if result is None:
            raise NotFoundError("Pet schedule not found.")

    async def _require_schedule_access(self, actor: Actor, schedule_id: int) -> None:
        if actor.actor_type not in (ActorType.ADMIN_USER, ActorType.MOBILE_USER):
            raise ForbiddenError("You do not have permission to access this pet schedule.")

        if actor.actor_type == ActorType.MOBILE_USER:
            await self._require_schedule_ownership(actor, schedule_id)

    async def _get_pet_schedule(
        self, schedule_id: int, actor: Actor | None = None
    ) -> PetSchedule | None:
        query = (
            select(PetSchedule)
            .where(
                PetSchedule.id == schedule_id,
                PetSchedule.is_deleted.is_(False),
            )
        )

        if actor is not None and actor.actor_type == ActorType.MOBILE_USER:
            query = (
                query
                .join(Pet, Pet.id == PetSchedule.pet_id)
                .where(
                    Pet.owner_id == actor.id,
                    Pet.is_deleted.is_(False),
                )
            )

        return (await self.db.execute(query)).scalar_one_or_none()

    async def create(
        self,
        *,
        actor: Actor,
        pet_id: int,
        schedule_input: PetScheduleCreate,
    ) -> PetScheduleRead:
        await self._require_pet_access(actor, pet_id)

        schedule_model = PetSchedule(
            pet_id=pet_id,
            next_schedule_at=schedule_input.scheduled_at,
            **schedule_input.model_dump(),
        )
        self.db.add(schedule_model)

        try:
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to create the pet schedule. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to create the pet schedule."
            ) from error

        await self.db.refresh(schedule_model)
        return PetScheduleRead.model_validate(schedule_model)

    async def search(
        self,
        *,
        actor: Actor,
        search_request: SearchRequest,
        user_id: int | None = None,
        pet_id: int | None = None,
    ) -> PaginatedResponse[PetScheduleRead]:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to search pet schedules.")

        if actor.actor_type == ActorType.MOBILE_USER:
            user_id = actor.id

        blacklisted = (
            self.MOBILE_SEARCH_BLACKLIST_COLUMNS
            if actor.actor_type == ActorType.MOBILE_USER
            else self.ADMIN_SEARCH_BLACKLIST_COLUMNS
        )

        if (
            actor.actor_type == ActorType.MOBILE_USER
            or (actor.actor_type == ActorType.ADMIN_USER and user_id is not None)
        ):
            base_query = (
                select(PetSchedule)
                .join(Pet, Pet.id == PetSchedule.pet_id)
                .where(
                    Pet.owner_id == user_id,
                    Pet.is_deleted.is_(False),
                    PetSchedule.is_deleted.is_(False),
                )
            )
        else:
            base_query = select(PetSchedule).where(PetSchedule.is_deleted.is_(False))

        if pet_id is not None:
            base_query = base_query.where(PetSchedule.pet_id == pet_id)

        engine = SearchEngine(
            db=self.db,
            model=PetSchedule,
            blacklisted_columns=blacklisted,
            allowed_ops=self.ALLOWED_FILTER_OPERATORS_BY_COLUMN,
            column_order_map=None,
            sortable_columns=self.SEARCH_SORTABLE_COLUMNS,
            max_in_list_size=100,
            max_depth=1,
        )

        result = await engine.search(
            base_query=base_query,
            values=search_request,
            serializer=PetScheduleRead.model_validate,
        )

        return PaginatedResponse[PetScheduleRead](
            data=result.data,
            total_count=result.total_count,
            has_more=(result.page * result.items_per_page) < result.total_count,
            page=result.page,
            items_per_page=result.items_per_page,
        )

    async def get_pet_schedules(
        self,
        *,
        actor: Actor,
        page: int,
        items_per_page: int,
        user_id: int | None = None,
        pet_id: int | None = None,
    ) -> PaginatedResponse[PetScheduleRead]:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view pet schedules.")

        if actor.actor_type == ActorType.MOBILE_USER:
            user_id = actor.id

        base_query = (
            select(PetSchedule)
            .join(Pet, Pet.id == PetSchedule.pet_id)
            .where(
                Pet.is_deleted.is_(False),
                PetSchedule.is_deleted.is_(False),
            )
        )

        if user_id is not None:
            base_query = base_query.where(Pet.owner_id == user_id)

        if pet_id is not None:
            base_query = base_query.where(PetSchedule.pet_id == pet_id)

        db_schedules = (
            await self.db.execute(
                base_query
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

        return PaginatedResponse[PetScheduleRead](
            data=[PetScheduleRead.model_validate(schedule) for schedule in db_schedules],
            total_count=total_count,
            has_more=(page * items_per_page) < total_count,
            page=page,
            items_per_page=items_per_page,
        )

    async def get_pet_schedule(
        self,
        *,
        actor: Actor,
        schedule_id: int,
    ) -> PetScheduleRead:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view this pet schedule.")

        db_schedule = await self._get_pet_schedule(schedule_id, actor)
        if db_schedule is None:
            raise NotFoundError("Pet schedule not found.")

        return PetScheduleRead.model_validate(db_schedule)

    async def update(
        self,
        *,
        actor: Actor,
        schedule_id: int,
        schedule_input: PetScheduleUpdate,
    ) -> None:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to update this pet schedule.")

        db_schedule = await self._get_pet_schedule(schedule_id, actor)
        if db_schedule is None:
            raise NotFoundError("Pet schedule not found.")

        apply_partial_update(target=db_schedule, input=schedule_input)

        try:
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update the pet schedule."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update the pet schedule."
            ) from error

    async def soft_delete(
        self,
        *,
        actor: Actor,
        schedule_id: int,
    ) -> None:
        await self._require_schedule_access(actor, schedule_id)

        statement = (
            update(PetSchedule)
            .where(
                PetSchedule.id == schedule_id,
                PetSchedule.is_deleted.is_(False),
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
                "Failed to delete the pet schedule. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete the pet schedule."
            ) from error

    async def bulk_soft_delete(
        self,
        *,
        actor: Actor,
        schedule_ids: set[int],
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to delete pet schedules.")

        if not schedule_ids:
            return

        statement = (
            update(PetSchedule)
            .where(
                PetSchedule.id == any_(list(schedule_ids)),
                PetSchedule.is_deleted.is_(False),
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
                "Failed to delete pet schedules. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete pet schedules."
            ) from error

    async def hard_delete(
        self,
        *,
        actor: Actor,
        schedule_id: int,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete the pet schedule.")

        statement = (
            delete(PetSchedule)
            .where(PetSchedule.id == schedule_id)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete the pet schedule. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete the pet schedule."
            ) from error

    async def bulk_hard_delete(
        self,
        *,
        actor: Actor,
        schedule_ids: set[int],
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete pet schedules.")

        if not schedule_ids:
            return

        statement = (
            delete(PetSchedule)
            .where(PetSchedule.id == any_(list(schedule_ids)))
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete pet schedules. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete pet schedules."
            ) from error
