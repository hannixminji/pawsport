from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from fastcrud import compute_offset
from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions.http_exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from ..core.query.enums import FilterOp, SortOrder
from ..models.pet import Pet
from ..models.pet_allergy import AllergenType, AllergySeverity, PetAllergy
from ..models.user import User
from ..schemas.pet_allergy import PetAllergyCreate, PetAllergyRead, PetAllergyUpdate
from ..schemas.pet_allergy_search import (
    PetAllergyFilterField,
    PetAllergySearchRequest,
    PetAllergySortBy,
    WhereGroup,
    WhereNode,
    WhereNot,
    WhereRule,
)
from ..schemas.user import UserRead

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PetAllergyService:
    db: AsyncSession

    async def _get_user_id_by_username(self, username: str) -> int:
        db_user_id = (
            await self.db.execute(
                select(User.id).where(
                    User.username == username,
                    ~User.is_deleted,
                )
            )
        ).scalar_one_or_none()
        if not db_user_id:
            raise NotFoundException("User not found")
        return int(db_user_id)

    async def _get_pet_id_for_user(self, pet_id: int, user_id: int) -> int:
        db_pet_id = (
            await self.db.execute(
                select(Pet.id).where(
                    Pet.id == pet_id,
                    Pet.owner_id == user_id,
                    ~Pet.is_deleted,
                )
            )
        ).scalar_one_or_none()
        if not db_pet_id:
            raise NotFoundException("Pet not found")
        return int(db_pet_id)

    def _enforce_owner(self, current_user: UserRead, user_id: int) -> None:
        if int(current_user.id) != int(user_id):
            raise ForbiddenException()

    async def write_pet_allergy(
        self,
        *,
        username: str,
        pet_id: int,
        allergy: PetAllergyCreate,
        current_user: UserRead,
    ) -> PetAllergyRead:
        user_id = await self._get_user_id_by_username(username)
        self._enforce_owner(current_user, user_id)
        resolved_pet_id = await self._get_pet_id_for_user(pet_id, user_id)

        model = PetAllergy(**allergy.model_dump(), pet_id=resolved_pet_id)
        self.db.add(model)

        try:
            await self.db.commit()
        except IntegrityError as error:
            await self.db.rollback()

            if "uq_pet_allergy_pet_id_allergen_active" in str(getattr(error, "orig", "")):
                raise BadRequestException("This allergen already exists for this pet.")

            raise BadRequestException("Unable to create the allergy. Please try again.")
        except SQLAlchemyError as error:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred while creating the pet allergy. Please try again later.",
            ) from error

        await self.db.refresh(model)
        return PetAllergyRead.model_validate(model)

    async def search_pet_allergies(
        self,
        *,
        username: str,
        pet_id: int,
        values: PetAllergySearchRequest,
    ) -> dict[str, Any]:
        user_id = await self._get_user_id_by_username(username)
        resolved_pet_id = await self._get_pet_id_for_user(pet_id, user_id)

        filter_columns = {
            PetAllergyFilterField.ALLERGEN: PetAllergy.allergen,
            PetAllergyFilterField.ALLERGEN_TYPE: PetAllergy.allergen_type,
            PetAllergyFilterField.SEVERITY_LEVEL: PetAllergy.severity_level,
        }

        sort_columns = {
            PetAllergySortBy.ALLERGEN: PetAllergy.allergen,
            PetAllergySortBy.ALLERGEN_TYPE: PetAllergy.allergen_type,
            PetAllergySortBy.SEVERITY_LEVEL: PetAllergy.severity_level,
            PetAllergySortBy.CREATED_AT: PetAllergy.created_at,
        }

        allowed_ops = {
            PetAllergyFilterField.ALLERGEN: frozenset({FilterOp.EQ, FilterOp.ILIKE, FilterOp.IN}),
            PetAllergyFilterField.ALLERGEN_TYPE: frozenset({FilterOp.EQ, FilterOp.IN}),
            PetAllergyFilterField.SEVERITY_LEVEL: frozenset({FilterOp.EQ, FilterOp.IN}),
        }

        where_clauses: list[Any] = [
            PetAllergy.pet_id == resolved_pet_id,
            ~PetAllergy.is_deleted,
        ]

        if values.where is not None:
            where_clauses.append(self.build_where(values.where, filter_columns, allowed_ops))

        sort_column = sort_columns.get(values.sort_by)
        if not sort_column:
            raise BadRequestException("Invalid sort_by field.")

        order_by_clause = sort_column.asc() if values.sort_order == SortOrder.ASC else sort_column.desc()

        items = (
            await self.db.execute(
                select(PetAllergy)
                .where(*where_clauses)
                .order_by(order_by_clause)
                .offset(compute_offset(values.page, values.items_per_page))
                .limit(values.items_per_page)
            )
        ).scalars().all()

        total_count = (
            await self.db.execute(
                select(func.count())
                .select_from(PetAllergy)
                .where(*where_clauses)
            )
        ).scalar_one()

        return {
            "data": [PetAllergyRead.model_validate(item) for item in items],
            "total_count": int(total_count),
        }

    async def read_pet_allergies(
        self,
        *,
        username: str,
        pet_id: int,
        page: int = 1,
        items_per_page: int = 10,
    ) -> dict[str, Any]:
        user_id = await self._get_user_id_by_username(username)
        resolved_pet_id = await self._get_pet_id_for_user(pet_id, user_id)

        items = (
            await self.db.execute(
                select(PetAllergy)
                .where(
                    PetAllergy.pet_id == resolved_pet_id,
                    ~PetAllergy.is_deleted,
                )
                .offset(compute_offset(page, items_per_page))
                .limit(items_per_page)
            )
        ).scalars().all()

        total_count = (
            await self.db.execute(
                select(func.count())
                .select_from(PetAllergy)
                .where(
                    PetAllergy.pet_id == resolved_pet_id,
                    ~PetAllergy.is_deleted,
                )
            )
        ).scalar_one()

        return {
            "data": [PetAllergyRead.model_validate(item) for item in items],
            "total_count": int(total_count),
        }

    async def read_pet_allergy(
        self,
        *,
        username: str,
        pet_id: int,
        id: int,
    ) -> PetAllergyRead:
        user_id = await self._get_user_id_by_username(username)
        resolved_pet_id = await self._get_pet_id_for_user(pet_id, user_id)

        item = (
            await self.db.execute(
                select(PetAllergy).where(
                    PetAllergy.id == id,
                    PetAllergy.pet_id == resolved_pet_id,
                    ~PetAllergy.is_deleted,
                )
            )
        ).scalar_one_or_none()
        if not item:
            raise NotFoundException("Pet allergy not found")

        return PetAllergyRead.model_validate(item)

    async def patch_pet_allergy(
        self,
        *,
        username: str,
        pet_id: int,
        id: int,
        values: PetAllergyUpdate,
        current_user: UserRead,
    ) -> dict[str, str]:
        user_id = await self._get_user_id_by_username(username)
        self._enforce_owner(current_user, user_id)
        resolved_pet_id = await self._get_pet_id_for_user(pet_id, user_id)

        item = (
            await self.db.execute(
                select(PetAllergy).where(
                    PetAllergy.id == id,
                    PetAllergy.pet_id == resolved_pet_id,
                    ~PetAllergy.is_deleted,
                )
            )
        ).scalar_one_or_none()
        if not item:
            raise NotFoundException("Pet allergy not found")

        for field, value in values.model_dump(exclude_unset=True).items():
            setattr(item, field, value)

        item.updated_at = datetime.now(UTC)

        try:
            await self.db.commit()
        except IntegrityError as error:
            await self.db.rollback()

            if "uq_pet_allergy_pet_id_allergen_active" in str(getattr(error, "orig", "")):
                raise BadRequestException("This allergen already exists for this pet.")

            raise BadRequestException("Unable to update the allergy. Please try again.")
        except SQLAlchemyError as error:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred while updating the pet allergy. Please try again later.",
            ) from error

        return {"message": "Pet allergy updated"}

    async def erase_pet_allergy(
        self,
        *,
        username: str,
        pet_id: int,
        id: int,
        current_user: UserRead,
    ) -> dict[str, str]:
        user_id = await self._get_user_id_by_username(username)
        self._enforce_owner(current_user, user_id)
        resolved_pet_id = await self._get_pet_id_for_user(pet_id, user_id)

        item = (
            await self.db.execute(
                select(PetAllergy).where(
                    PetAllergy.id == id,
                    PetAllergy.pet_id == resolved_pet_id,
                    ~PetAllergy.is_deleted,
                )
            )
        ).scalar_one_or_none()
        if not item:
            raise NotFoundException("Pet allergy not found")

        now = datetime.now(UTC)
        item.is_deleted = True
        item.deleted_at = now
        self.db.add(item)

        try:
            await self.db.commit()
        except SQLAlchemyError as error:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred while deleting the pet allergy. Please try again later.",
            ) from error

        return {"message": "Pet allergy deleted"}

    async def erase_db_pet_allergy(
        self,
        *,
        username: str,
        pet_id: int,
        id: int,
    ) -> dict[str, str]:
        user_id = await self._get_user_id_by_username(username)
        resolved_pet_id = await self._get_pet_id_for_user(pet_id, user_id)

        item = (
            await self.db.execute(
                select(PetAllergy).where(
                    PetAllergy.id == id,
                    PetAllergy.pet_id == resolved_pet_id,
                    ~PetAllergy.is_deleted,
                )
            )
        ).scalar_one_or_none()
        if not item:
            raise NotFoundException("Pet allergy not found")

        try:
            await self.db.delete(item)
            await self.db.commit()
        except SQLAlchemyError as error:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred while deleting the pet allergy. Please try again later.",
            ) from error

        return {"message": "Pet allergy deleted from the database"}

    def build_where(
        self,
        node: WhereNode,
        filter_columns: dict[PetAllergyFilterField, Any],
        allowed_ops: dict[PetAllergyFilterField, frozenset[FilterOp]],
    ):  # noqa: C901
        if isinstance(node, WhereRule):
            column = filter_columns.get(node.field)
            if not column:
                raise BadRequestException("Invalid filter field.")

            ops = allowed_ops.get(node.field, frozenset())
            if node.op not in ops:
                raise BadRequestException("Invalid filter operator for field.")

            value = node.value

            if node.field == PetAllergyFilterField.ALLERGEN_TYPE:
                value = self._coerce_allergen_type(value, node.op)

            if node.field == PetAllergyFilterField.SEVERITY_LEVEL:
                value = self._coerce_severity(value, node.op)

            if node.op == FilterOp.EQ:
                return column == value

            if node.op == FilterOp.ILIKE:
                if not isinstance(value, str):
                    raise BadRequestException("ILIKE value must be a string.")
                return column.ilike(f"%{value}%")

            if node.op == FilterOp.GTE:
                return column >= value

            if node.op == FilterOp.LTE:
                return column <= value

            if node.op == FilterOp.IN:
                if not isinstance(value, list) or not value:
                    raise BadRequestException("IN value must be a non-empty list.")
                return column.in_(value)

            raise BadRequestException("Invalid filter operator.")

        if isinstance(node, WhereNot):
            return not_(self.build_where(node.condition, filter_columns, allowed_ops))

        if isinstance(node, WhereGroup):
            children = [self.build_where(child, filter_columns, allowed_ops) for child in node.conditions]
            return and_(*children) if node.op == "and" else or_(*children)

        raise BadRequestException("Invalid where clause.")

    def _coerce_allergen_type(self, value: Any, op: FilterOp) -> Any:
        if op == FilterOp.EQ:
            if isinstance(value, str):
                try:
                    value = AllergenType(value.lower())
                except ValueError:
                    raise BadRequestException("Invalid allergen_type.")
            if not isinstance(value, AllergenType):
                raise BadRequestException("Invalid allergen_type.")
            return value

        if op == FilterOp.IN:
            if not isinstance(value, list) or not value:
                raise BadRequestException("IN value must be a non-empty list.")
            converted: list[AllergenType] = []
            for item in value:
                if not isinstance(item, str):
                    raise BadRequestException("allergen_type IN values must be strings.")
                try:
                    converted.append(AllergenType(item.lower()))
                except ValueError:
                    raise BadRequestException("Invalid allergen_type.")
            return converted

        raise BadRequestException("allergen_type only supports eq or in.")

    def _coerce_severity(self, value: Any, op: FilterOp) -> Any:
        if op == FilterOp.EQ:
            if isinstance(value, str):
                try:
                    value = AllergySeverity(value.lower())
                except ValueError:
                    raise BadRequestException("Invalid severity_level.")
            if not isinstance(value, AllergySeverity):
                raise BadRequestException("Invalid severity_level.")
            return value

        if op == FilterOp.IN:
            if not isinstance(value, list) or not value:
                raise BadRequestException("IN value must be a non-empty list.")
            converted: list[AllergySeverity] = []
            for item in value:
                if not isinstance(item, str):
                    raise BadRequestException("severity_level IN values must be strings.")
                try:
                    converted.append(AllergySeverity(item.lower()))
                except ValueError:
                    raise BadRequestException("Invalid severity_level.")
            return converted

        raise BadRequestException("severity_level only supports eq or in.")
