import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Union

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastcrud import PaginatedListResponse, compute_offset, paginated_response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.dependencies import get_authenticated_superuser, get_authenticated_user
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from ...core.utils.cache import cache
from ...models.pet import Pet
from ...models.pet_allergy import AllergenType, AllergySeverity, PetAllergy
from ...models.user import User
from ...schemas.pet_allergy import PetAllergyCreate, PetAllergyRead, PetAllergyUpdate
from ...schemas.user import UserRead

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["pet_allergies"])


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class PetAllergySortBy(StrEnum):
    ALLERGEN = "allergen"
    ALLERGEN_TYPE = "allergen_type"
    SEVERITY_LEVEL = "severity_level"
    CREATED_AT = "created_at"


class FilterOp(StrEnum):
    EQ = "eq"
    ILIKE = "ilike"
    GTE = "gte"
    LTE = "lte"
    IN = "in"


class PetAllergyFilterField(StrEnum):
    ALLERGEN = "allergen"
    ALLERGEN_TYPE = "allergen_type"
    SEVERITY_LEVEL = "severity_level"


class WhereRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["rule"]
    field: PetAllergyFilterField
    op: FilterOp
    value: Any


class WhereGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["group"]
    op: Literal["and", "or"]
    conditions: list["WhereNode"] = Field(min_length=1, max_length=50)


class WhereNot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["not"]
    condition: "WhereNode"


WhereNode = Annotated[Union[WhereRule, WhereGroup, WhereNot], Field(discriminator="type")]


class PetAllergySearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1)
    items_per_page: int = Field(10, ge=1, le=100)

    sort_by: PetAllergySortBy = PetAllergySortBy.CREATED_AT
    sort_order: SortOrder = SortOrder.DESC

    where: WhereNode | None = None

    @model_validator(mode="after")
    def limit_complexity(self):
        def count_nodes(node: WhereNode, depth: int = 0) -> int:
            if depth > 10:
                raise ValueError("where is too deeply nested")

            if isinstance(node, WhereRule):
                return 1

            if isinstance(node, WhereNot):
                return 1 + count_nodes(node.condition, depth + 1)

            total = 1
            for child in node.conditions:
                total += count_nodes(child, depth + 1)
            return total

        if self.where is not None:
            total = count_nodes(self.where, 0)
            if total > 200:
                raise ValueError("where is too large")
        return self


def build_where(node: WhereNode, filter_columns: dict[PetAllergyFilterField, Any]):  # noqa: C901
    if isinstance(node, WhereRule):
        column = filter_columns[node.field]
        value = node.value

        if node.field == PetAllergyFilterField.ALLERGEN_TYPE:
            if node.op == FilterOp.EQ:
                if isinstance(value, str):
                    try:
                        value = AllergenType(value.lower())
                    except ValueError:
                        raise BadRequestException("Invalid allergen_type.")
                if not isinstance(value, AllergenType):
                    raise BadRequestException("Invalid allergen_type.")

            elif node.op == FilterOp.IN:
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
                value = converted

            else:
                raise BadRequestException("allergen_type only supports eq or in.")

        if node.field == PetAllergyFilterField.SEVERITY_LEVEL:
            if node.op == FilterOp.EQ:
                if isinstance(value, str):
                    try:
                        value = AllergySeverity(value.lower())
                    except ValueError:
                        raise BadRequestException("Invalid severity_level.")
                if not isinstance(value, AllergySeverity):
                    raise BadRequestException("Invalid severity_level.")

            elif node.op == FilterOp.IN:
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
                value = converted

            else:
                raise BadRequestException("severity_level only supports eq or in.")

        if node.field == PetAllergyFilterField.ALLERGEN:
            if node.op not in {FilterOp.EQ, FilterOp.ILIKE, FilterOp.IN}:
                raise BadRequestException("allergen only supports eq, ilike, or in.")

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
        return not_(build_where(node.condition, filter_columns))

    children = [build_where(child, filter_columns) for child in node.conditions]
    return and_(*children) if node.op == "and" else or_(*children)


@router.post("/{username}/pet/{pet_id}/allergy", response_model=PetAllergyRead, status_code=201)
async def write_pet_allergy(
    request: Request,
    username: str,
    pet_id: int,
    allergy: PetAllergyCreate,
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> PetAllergyRead:
    db_user_id = (
        await db.execute(
            select(User.id)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    if current_user.id != db_user_id:
        raise ForbiddenException()

    db_pet_id = (
        await db.execute(
            select(Pet.id)
            .where(
                Pet.id == pet_id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_id:
        raise NotFoundException("Pet not found")

    pet_allergy_model = PetAllergy(**allergy.model_dump(), pet_id=db_pet_id)
    db.add(pet_allergy_model)

    try:
        await db.commit()

    except IntegrityError as error:
        await db.rollback()

        if "uq_pet_allergy_pet_id_allergen_active" in str(getattr(error, "orig", "")):
            raise BadRequestException("This allergen already exists for this pet.")

        raise BadRequestException("Unable to create the allergy. Please try again.")

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the pet allergy. Please try again later."
        )

    await db.refresh(pet_allergy_model)

    return PetAllergyRead.model_validate(pet_allergy_model)


@router.post(
    "/{username}/pet/{pet_id}/allergies/search",
    response_model=PaginatedListResponse[PetAllergyRead],
)
async def search_pet_allergies(
    request: Request,
    username: str,
    pet_id: int,
    values: PetAllergySearchRequest,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, Any]:
    db_user_id = (
        await db.execute(
            select(User.id)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    db_pet_id = (
        await db.execute(
            select(Pet.id)
            .where(
                Pet.id == pet_id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_id:
        raise NotFoundException("Pet not found")

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

    where_clauses = [
        PetAllergy.pet_id == db_pet_id,
        ~PetAllergy.is_deleted
    ]

    if values.where is not None:
        where_clauses.append(build_where(values.where, filter_columns))

    sort_column = sort_columns.get(values.sort_by)
    if not sort_column:
        raise BadRequestException("Invalid sort_by field.")

    order_by_clause = sort_column.asc() if values.sort_order == SortOrder.ASC else sort_column.desc()

    db_pet_allergies = (
        await db.execute(
            select(PetAllergy)
            .where(*where_clauses)
            .order_by(order_by_clause)
            .offset(compute_offset(values.page, values.items_per_page))
            .limit(values.items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(PetAllergy)
            .where(*where_clauses)
        )
    ).scalar_one()

    pet_allergies_data = {
        "data": [PetAllergyRead.model_validate(item) for item in db_pet_allergies],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(
        crud_data=pet_allergies_data,
        page=values.page,
        items_per_page=values.items_per_page
    )
    return response


@router.get("/{username}/pet/{pet_id}/allergies", response_model=PaginatedListResponse[PetAllergyRead])
@cache(
    key_prefix="{username}_pet_{pet_id}_allergies:page_{page}:items_per_page:{items_per_page}",
    resource_id_name="pet_id",
    expiration=60,
)
async def read_pet_allergies(
    request: Request,
    username: str,
    pet_id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    page: int = 1,
    items_per_page: int = 10,
) -> dict[str, Any]:
    db_user_id = (
        await db.execute(
            select(User.id)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    db_pet_id = (
        await db.execute(
            select(Pet.id)
            .where(
                Pet.id == pet_id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_id:
        raise NotFoundException("Pet not found")

    db_pet_allergies = (
        await db.execute(
            select(PetAllergy)
            .where(
                PetAllergy.pet_id == db_pet_id,
                ~PetAllergy.is_deleted
            )
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(PetAllergy)
            .where(
                PetAllergy.pet_id == db_pet_id,
                ~PetAllergy.is_deleted
            )
        )
    ).scalar_one()

    pet_allergies_data = {
        "data": [PetAllergyRead.model_validate(allergy) for allergy in db_pet_allergies],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(
        crud_data=pet_allergies_data,
        page=page,
        items_per_page=items_per_page
    )
    return response


@router.get("/{username}/pet/{pet_id}/allergy/{id}", response_model=PetAllergyRead)
@cache(key_prefix="{username}_pet_{pet_id}_allergy_cache", resource_id_name="id")
async def read_pet_allergy(
    request: Request,
    username: str,
    pet_id: int,
    id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> PetAllergyRead:
    db_user_id = (
        await db.execute(
            select(User.id)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    db_pet_id = (
        await db.execute(
            select(Pet.id)
            .where(
                Pet.id == pet_id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_id:
        raise NotFoundException("Pet not found")

    db_pet_allergy = (
        await db.execute(
            select(PetAllergy)
            .where(
                PetAllergy.id == id,
                PetAllergy.pet_id == db_pet_id,
                ~PetAllergy.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_allergy:
        raise NotFoundException("Pet allergy not found")

    return PetAllergyRead.model_validate(db_pet_allergy)


@router.patch("/{username}/pet/{pet_id}/allergy/{id}")
@cache(
    "{username}_pet_{pet_id}_allergy_cache",
    resource_id_name="id",
    pattern_to_invalidate_extra=["{username}_pet_{pet_id}_allergies:*"],
)
async def patch_pet_allergy(
    request: Request,
    username: str,
    pet_id: int,
    id: int,
    values: PetAllergyUpdate,
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    db_user_id = (
        await db.execute(
            select(User.id)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    if current_user.id != db_user_id:
        raise ForbiddenException()

    db_pet_id = (
        await db.execute(
            select(Pet.id)
            .where(
                Pet.id == pet_id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_id:
        raise NotFoundException("Pet not found")

    db_pet_allergy = (
        await db.execute(
            select(PetAllergy)
            .where(
                PetAllergy.id == id,
                PetAllergy.pet_id == db_pet_id,
                ~PetAllergy.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_allergy:
        raise NotFoundException("Pet allergy not found")

    for field, value in values.model_dump(exclude_unset=True).items():
        setattr(db_pet_allergy, field, value)

    db_pet_allergy.updated_at = datetime.now(UTC)

    try:
        await db.commit()

    except IntegrityError as error:
        await db.rollback()

        if "uq_pet_allergy_pet_id_allergen_active" in str(getattr(error, "orig", "")):
            raise BadRequestException("This allergen already exists for this pet.")

        raise BadRequestException("Unable to update the allergy. Please try again.")

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the pet allergy. Please try again later."
        )

    return {"message": "Pet allergy updated"}


@router.delete("/{username}/pet/{pet_id}/allergy/{id}")
@cache(
    "{username}_pet_{pet_id}_allergy_cache",
    resource_id_name="id",
    to_invalidate_extra={"{username}_pet_{pet_id}_allergies": "{pet_id}"},
)
async def erase_pet_allergy(
    request: Request,
    username: str,
    pet_id: int,
    id: int,
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    db_user_id = (
        await db.execute(
            select(User.id)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    if current_user.id != db_user_id:
        raise ForbiddenException()

    db_pet_id = (
        await db.execute(
            select(Pet.id)
            .where(
                Pet.id == pet_id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_id:
        raise NotFoundException("Pet not found")

    db_pet_allergy = (
        await db.execute(
            select(PetAllergy)
            .where(
                PetAllergy.id == id,
                PetAllergy.pet_id == db_pet_id,
                ~PetAllergy.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_allergy:
        raise NotFoundException("Pet allergy not found")

    now = datetime.now(UTC)
    db_pet_allergy.is_deleted = True
    db_pet_allergy.deleted_at = now
    db.add(db_pet_allergy)

    try:
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the pet allergy. Please try again later."
        )

    return {"message": "Pet allergy deleted"}


@router.delete(
    "/{username}/pet/{pet_id}/db_pet_allergy/{id}",
    dependencies=[Depends(get_authenticated_superuser)]
)
@cache(
    "{username}_pet_{pet_id}_allergy_cache",
    resource_id_name="id",
    to_invalidate_extra={"{username}_pet_{pet_id}_allergies": "{pet_id}"},
)
async def erase_db_pet_allergy(
    request: Request,
    username: str,
    pet_id: int,
    id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    db_user_id = (
        await db.execute(
            select(User.id)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    db_pet_id = (
        await db.execute(
            select(Pet.id)
            .where(
                Pet.id == pet_id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_id:
        raise NotFoundException("Pet not found")

    db_pet_allergy = (
        await db.execute(
            select(PetAllergy)
            .where(
                PetAllergy.id == id,
                PetAllergy.pet_id == db_pet_id,
                ~PetAllergy.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_allergy:
        raise NotFoundException("Pet allergy not found")

    try:
        await db.delete(db_pet_allergy)
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the pet allergy. Please try again later."
        )

    return {"message": "Pet allergy deleted from the database"}
