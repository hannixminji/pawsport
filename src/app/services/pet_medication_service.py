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
from ..models.pet import Pet
from ..models.pet_medication import PetMedication
from ..schemas.pet_medication import (
    PetMedicationCreate,
    PetMedicationRead,
    PetMedicationUpdate,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PetMedicationService:
    db: AsyncSession

    MOBILE_SEARCH_BLACKLIST_COLUMNS = frozenset({
        "id",
        "pet_id",
        "dosage",
        "notes",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ADMIN_SEARCH_BLACKLIST_COLUMNS = frozenset({
        "id",
        "dosage",
        "notes",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ALLOWED_FILTER_OPERATORS_BY_COLUMN = {
        "pet_id": frozenset({
            FilterOp.EQ,
        }),
        "medication_name": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
        }),
        "administration_route": frozenset({
            FilterOp.EQ,
            FilterOp.IN,
        }),
        "frequency": frozenset({
            FilterOp.EQ,
            FilterOp.IN,
        }),
        "medication_status": frozenset({
            FilterOp.EQ,
            FilterOp.IN,
        }),
        "start_date": frozenset({
            FilterOp.LT,
            FilterOp.LTE,
            FilterOp.GT,
            FilterOp.GTE,
        }),
        "end_date": frozenset({
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
    SEARCH_SORTABLE_COLUMNS = {
        "medication_name",
        "start_date",
        "end_date",
        "created_at",
    }

    def _is_unique_constraint_violation(
        self, error: IntegrityError, constraint_name: str
    ) -> bool:
        original_exception = getattr(error, "orig", None)
        if not original_exception:
            return False

        violated_constraint_name = getattr(original_exception, "constraint_name", None)
        if isinstance(violated_constraint_name, str) and violated_constraint_name:
            return violated_constraint_name == constraint_name

        diagnostic = getattr(original_exception, "diag", None)
        diagnostic_constraint_name = getattr(diagnostic, "constraint_name", None)
        if isinstance(diagnostic_constraint_name, str) and diagnostic_constraint_name:
            return diagnostic_constraint_name == constraint_name

        return False

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

    async def _get_owned_medication_id(self, actor: Actor, medication_id: int) -> int | None:
        return (
            await self.db.execute(
                select(PetMedication.id)
                .join(Pet, Pet.id == PetMedication.pet_id)
                .where(
                    Pet.owner_id == actor.id,
                    Pet.is_deleted.is_(False),
                    PetMedication.id == medication_id,
                    PetMedication.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

    async def _require_medication_ownership(self, actor: Actor, medication_id: int) -> None:
        result = await self._get_owned_medication_id(actor, medication_id)
        if result is None:
            raise NotFoundError("Pet medication not found.")

    async def _require_medication_access(self, actor: Actor, medication_id: int) -> None:
        if actor.actor_type not in (ActorType.ADMIN_USER, ActorType.MOBILE_USER):
            raise ForbiddenError("You do not have permission to access this pet medication.")

        if actor.actor_type == ActorType.MOBILE_USER:
            await self._require_medication_ownership(actor, medication_id)

    async def _get_pet_medication(
        self, medication_id: int, actor: Actor | None = None
    ) -> PetMedication | None:
        query = (
            select(PetMedication)
            .where(
                PetMedication.id == medication_id,
                PetMedication.is_deleted.is_(False),
            )
        )

        if actor is not None and actor.actor_type == ActorType.MOBILE_USER:
            query = (
                query
                .join(Pet, Pet.id == PetMedication.pet_id)
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
        medication_input: PetMedicationCreate,
    ) -> PetMedicationRead:
        await self._require_pet_access(actor, pet_id)

        medication_model = PetMedication(pet_id=pet_id, **medication_input.model_dump())
        self.db.add(medication_model)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_pet_medication_pet_id_medication_name_active"):
                raise InvalidInputError("This medication already exists for this pet.")

            raise InvalidInputError("Unable to create the pet medication.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to create the pet medication. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to create the pet medication."
            ) from error

        await self.db.refresh(medication_model)
        return PetMedicationRead.model_validate(medication_model)

    async def search(
        self,
        *,
        actor: Actor,
        search_request: SearchRequest,
        user_id: int | None = None,
        pet_id: int | None = None,
    ) -> PaginatedResponse[PetMedicationRead]:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to search pet medications.")

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
                select(PetMedication)
                .join(Pet, Pet.id == PetMedication.pet_id)
                .where(
                    Pet.owner_id == user_id,
                    Pet.is_deleted.is_(False),
                    PetMedication.is_deleted.is_(False),
                )
            )
        else:
            base_query = select(PetMedication).where(PetMedication.is_deleted.is_(False))

        if pet_id is not None:
            base_query = base_query.where(PetMedication.pet_id == pet_id)

        engine = SearchEngine(
            db=self.db,
            model=PetMedication,
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
            serializer=PetMedicationRead.model_validate,
        )

        return PaginatedResponse[PetMedicationRead](
            data=result.data,
            total_count=result.total_count,
            has_more=(result.page * result.items_per_page) < result.total_count,
            page=result.page,
            items_per_page=result.items_per_page,
        )

    async def get_pet_medications(
        self,
        *,
        actor: Actor,
        page: int,
        items_per_page: int,
        user_id: int | None = None,
        pet_id: int | None = None,
    ) -> PaginatedResponse[PetMedicationRead]:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view pet medications.")

        if actor.actor_type == ActorType.MOBILE_USER:
            user_id = actor.id

        base_query = (
            select(PetMedication)
            .join(Pet, Pet.id == PetMedication.pet_id)
            .where(
                Pet.is_deleted.is_(False),
                PetMedication.is_deleted.is_(False),
            )
        )

        if user_id is not None:
            base_query = base_query.where(Pet.owner_id == user_id)

        if pet_id is not None:
            base_query = base_query.where(PetMedication.pet_id == pet_id)

        db_medications = (
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

        return PaginatedResponse[PetMedicationRead](
            data=[PetMedicationRead.model_validate(medication) for medication in db_medications],
            total_count=total_count,
            has_more=(page * items_per_page) < total_count,
            page=page,
            items_per_page=items_per_page,
        )

    async def get_pet_medication(
        self,
        *,
        actor: Actor,
        medication_id: int,
    ) -> PetMedicationRead:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view this pet medication.")

        db_medication = await self._get_pet_medication(medication_id, actor)
        if db_medication is None:
            raise NotFoundError("Pet medication not found.")

        return PetMedicationRead.model_validate(db_medication)

    async def update(
        self,
        *,
        actor: Actor,
        medication_id: int,
        medication_input: PetMedicationUpdate,
    ) -> None:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to update this pet medication.")

        db_medication = await self._get_pet_medication(medication_id, actor)
        if db_medication is None:
            raise NotFoundError("Pet medication not found.")

        apply_partial_update(target=db_medication, input=medication_input)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_pet_medication_pet_id_medication_name_active"):
                raise InvalidInputError("This medication already exists for this pet.")

            raise InvalidInputError("Unable to update the pet medication.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update the pet medication."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update the pet medication."
            ) from error

    async def soft_delete(
        self,
        *,
        actor: Actor,
        medication_id: int,
    ) -> None:
        await self._require_medication_access(actor, medication_id)

        statement = (
            update(PetMedication)
            .where(
                PetMedication.id == medication_id,
                PetMedication.is_deleted.is_(False),
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
                "Failed to delete the pet medication. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete the pet medication."
            ) from error

    async def bulk_soft_delete(
        self,
        *,
        actor: Actor,
        medication_ids: set[int],
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to delete pet medications.")

        if not medication_ids:
            return

        statement = (
            update(PetMedication)
            .where(
                PetMedication.id == any_(list(medication_ids)),
                PetMedication.is_deleted.is_(False),
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
                "Failed to delete pet medications. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete pet medications."
            ) from error

    async def hard_delete(
        self,
        *,
        actor: Actor,
        medication_id: int,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete the pet medication.")

        statement = (
            delete(PetMedication)
            .where(PetMedication.id == medication_id)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete the pet medication. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete the pet medication."
            ) from error

    async def bulk_hard_delete(
        self,
        *,
        actor: Actor,
        medication_ids: set[int],
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete pet medications.")

        if not medication_ids:
            return

        statement = (
            delete(PetMedication)
            .where(PetMedication.id == any_(list(medication_ids)))
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete pet medications. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete pet medications."
            ) from error
