import logging
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

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
from ..models.pet_allergy import PetAllergy
from ..schemas.pet_allergy import PetAllergyCreate, PetAllergyRead, PetAllergyUpdate

LOGGER = logging.getLogger(__name__)

EnumT = TypeVar("EnumT", bound=Enum)


@dataclass(slots=True)
class PetAllergyService:
    db: AsyncSession

    MOBILE_SEARCH_BLACKLIST_COLUMNS = frozenset({
        "id",
        "pet_id",
        "reaction",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ADMIN_SEARCH_BLACKLIST_COLUMNS = frozenset({
        "id",
        "reaction",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ALLOWED_FILTER_OPERATORS_BY_COLUMN = {
        "pet_id": frozenset({
            FilterOp.EQ,
        }),
        "allergen": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
        }),
        "allergen_type": frozenset({
            FilterOp.EQ,
            FilterOp.IN,
        }),
        "severity": frozenset({
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
        "allergen",
        "created_at"
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

    async def _get_owned_allergy_id(self, actor: Actor, allergy_id: int) -> int | None:
        return (
            await self.db.execute(
                select(PetAllergy.id)
                .join(Pet, Pet.id == PetAllergy.pet_id)
                .where(
                    Pet.owner_id == actor.id,
                    Pet.is_deleted.is_(False),
                    PetAllergy.id == allergy_id,
                    PetAllergy.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

    async def _require_allergy_ownership(self, actor: Actor, allergy_id: int) -> None:
        result = await self._get_owned_allergy_id(actor, allergy_id)
        if result is None:
            raise NotFoundError("Pet allergy not found.")

    async def _require_allergy_access(self, actor: Actor, allergy_id: int) -> None:
        if actor.actor_type not in (ActorType.ADMIN_USER, ActorType.MOBILE_USER):
            raise ForbiddenError("You do not have permission to access this pet allergy.")

        if actor.actor_type == ActorType.MOBILE_USER:
            await self._require_allergy_ownership(actor, allergy_id)

    async def _get_pet_allergy(self, allergy_id: int, actor: Actor | None = None) -> PetAllergy | None:
        query = (
            select(PetAllergy)
            .where(
                PetAllergy.id == allergy_id,
                PetAllergy.is_deleted.is_(False),
            )
        )

        if actor is not None and actor.actor_type == ActorType.MOBILE_USER:
            query = (
                query
                .join(Pet, Pet.id == PetAllergy.pet_id)
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
        allergy_input: PetAllergyCreate,
    ) -> PetAllergyRead:
        await self._require_pet_access(actor, pet_id)

        allergy_model = PetAllergy(pet_id=pet_id, **allergy_input.model_dump())
        self.db.add(allergy_model)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_pet_allergy_pet_id_allergen_active"):
                raise InvalidInputError("This allergen already exists for this pet.")

            raise InvalidInputError("Unable to create the pet allergy.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to create the pet allergy. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to create the pet allergy."
            ) from error

        await self.db.refresh(allergy_model)
        return PetAllergyRead.model_validate(allergy_model)

    async def search(
        self,
        *,
        actor: Actor,
        search_request: SearchRequest,
        user_id: int | None = None,
        pet_id: int | None = None,
    ) -> PaginatedResponse[PetAllergyRead]:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to search pet allergies.")

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
                select(PetAllergy)
                .join(Pet, Pet.id == PetAllergy.pet_id)
                .where(
                    Pet.owner_id == user_id,
                    Pet.is_deleted.is_(False),
                    PetAllergy.is_deleted.is_(False),
                )
            )
        else:
            base_query = select(PetAllergy).where(PetAllergy.is_deleted.is_(False))

        if pet_id is not None:
            base_query = base_query.where(PetAllergy.pet_id == pet_id)

        engine = SearchEngine(
            db=self.db,
            model=PetAllergy,
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
            serializer=PetAllergyRead.model_validate,
        )

        return PaginatedResponse[PetAllergyRead](
            data=result.data,
            total_count=result.total_count,
            has_more=(result.page * result.items_per_page) < result.total_count,
            page=result.page,
            items_per_page=result.items_per_page,
        )

    async def get_pet_allergies(
        self,
        *,
        actor: Actor,
        page: int,
        items_per_page: int,
        user_id: int | None = None,
        pet_id: int | None = None,
    ) -> PaginatedResponse[PetAllergyRead]:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view pet allergies.")

        if actor.actor_type == ActorType.MOBILE_USER:
            user_id = actor.id

        base_query = (
            select(PetAllergy)
            .join(Pet, Pet.id == PetAllergy.pet_id)
            .where(
                Pet.is_deleted.is_(False),
                PetAllergy.is_deleted.is_(False),
            )
        )

        if user_id is not None:
            base_query = base_query.where(Pet.owner_id == user_id)

        if pet_id is not None:
            base_query = base_query.where(PetAllergy.pet_id == pet_id)

        db_allergies = (
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

        return PaginatedResponse[PetAllergyRead](
            data=[PetAllergyRead.model_validate(allergy) for allergy in db_allergies],
            total_count=total_count,
            has_more=(page * items_per_page) < total_count,
            page=page,
            items_per_page=items_per_page,
        )

    async def get_pet_allergy(
        self,
        *,
        actor: Actor,
        allergy_id: int,
    ) -> PetAllergyRead:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view this pet allergy.")

        db_allergy = await self._get_pet_allergy(allergy_id, actor)
        if db_allergy is None:
            raise NotFoundError("Pet allergy not found.")

        return PetAllergyRead.model_validate(db_allergy)

    async def update(
        self,
        *,
        actor: Actor,
        allergy_id: int,
        allergy_input: PetAllergyUpdate,
    ) -> None:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to update this pet allergy.")

        db_allergy = await self._get_pet_allergy(allergy_id, actor)
        if db_allergy is None:
            raise NotFoundError("Pet allergy not found.")

        apply_partial_update(target=db_allergy, input=allergy_input)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_pet_allergy_pet_id_allergen_active"):
                raise InvalidInputError("This allergen already exists for this pet.")

            raise InvalidInputError("Unable to update the pet allergy.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update the pet allergy."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update the pet allergy."
            ) from error

    async def soft_delete(
        self,
        *,
        actor: Actor,
        allergy_id: int,
    ) -> None:
        await self._require_allergy_access(actor, allergy_id)

        statement = (
            update(PetAllergy)
            .where(
                PetAllergy.id == allergy_id,
                PetAllergy.is_deleted.is_(False),
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
                "Failed to delete the pet allergy. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete the pet allergy."
            ) from error

    async def bulk_soft_delete(
        self,
        *,
        actor: Actor,
        allergy_ids: set[int],
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to delete pet allergies.")

        if not allergy_ids:
            return

        statement = (
            update(PetAllergy)
            .where(
                PetAllergy.id == any_(list(allergy_ids)),
                PetAllergy.is_deleted.is_(False),
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
                "Failed to delete pet allergies. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete pet allergies."
            ) from error

    async def hard_delete(
        self,
        *,
        actor: Actor,
        allergy_id: int,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete the pet allergy.")

        statement = (
            delete(PetAllergy)
            .where(PetAllergy.id == allergy_id)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete the pet allergy. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete the pet allergy."
            ) from error

    async def bulk_hard_delete(
        self,
        *,
        actor: Actor,
        allergy_ids: set[int],
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete pet allergies.")

        if not allergy_ids:
            return

        statement = (
            delete(PetAllergy)
            .where(PetAllergy.id == any_(list(allergy_ids)))
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete pet allergies. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete pet allergies."
            ) from error
