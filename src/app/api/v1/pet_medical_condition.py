import logging
from datetime import UTC, date, datetime
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
from ...models.pet_medical_condition import (
    MedicalConditionSeverity,
    MedicalConditionStatus,
    PetMedicalCondition,
)
from ...models.user import User
from ...schemas.pet_medical_condition import (
    PetMedicalConditionCreate,
    PetMedicalConditionRead,
    PetMedicalConditionUpdate,
)
from ...schemas.user import UserRead

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["pet_medical_conditions"])


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class PetMedicalConditionSortBy(StrEnum):
    CONDITION_NAME = "condition_name"
    SEVERITY_LEVEL = "severity_level"
    CONDITION_STATUS = "condition_status"
    DIAGNOSIS_DATE = "diagnosis_date"
    CREATED_AT = "created_at"


class FilterOp(StrEnum):
    EQ = "eq"
    ILIKE = "ilike"
    GTE = "gte"
    LTE = "lte"
    IN = "in"


class PetMedicalConditionFilterField(StrEnum):
    CONDITION_NAME = "condition_name"
    SEVERITY_LEVEL = "severity_level"
    CONDITION_STATUS = "condition_status"
    DIAGNOSIS_DATE = "diagnosis_date"


class WhereRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["rule"]
    field: PetMedicalConditionFilterField
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


class PetMedicalConditionSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1)
    items_per_page: int = Field(10, ge=1, le=100)

    sort_by: PetMedicalConditionSortBy = PetMedicalConditionSortBy.CREATED_AT
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


def _parse_iso_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    if not isinstance(value, str):
        raise BadRequestException("Date filter value must be YYYY-MM-DD.")

    try:
        return date.fromisoformat(value)
    except ValueError:
        raise BadRequestException("Invalid date format. Use YYYY-MM-DD.")


def build_where(node: WhereNode, filter_columns: dict[PetMedicalConditionFilterField, Any]):  # noqa: C901
    if isinstance(node, WhereRule):
        column = filter_columns[node.field]
        value = node.value

        if node.field == PetMedicalConditionFilterField.SEVERITY_LEVEL:
            if node.op == FilterOp.EQ:
                if isinstance(value, str):
                    try:
                        value = MedicalConditionSeverity(value.lower())
                    except ValueError:
                        raise BadRequestException("Invalid severity_level.")
                if not isinstance(value, MedicalConditionSeverity):
                    raise BadRequestException("Invalid severity_level.")

            elif node.op == FilterOp.IN:
                if not isinstance(value, list) or not value:
                    raise BadRequestException("IN value must be a non-empty list.")
                converted: list[MedicalConditionSeverity] = []
                for item in value:
                    if not isinstance(item, str):
                        raise BadRequestException("severity_level IN values must be strings.")
                    try:
                        converted.append(MedicalConditionSeverity(item.lower()))
                    except ValueError:
                        raise BadRequestException("Invalid severity_level.")
                value = converted

            else:
                raise BadRequestException("severity_level only supports eq or in.")

        if node.field == PetMedicalConditionFilterField.CONDITION_STATUS:
            if node.op == FilterOp.EQ:
                if isinstance(value, str):
                    try:
                        value = MedicalConditionStatus(value.lower())
                    except ValueError:
                        raise BadRequestException("Invalid condition_status.")
                if not isinstance(value, MedicalConditionStatus):
                    raise BadRequestException("Invalid condition_status.")

            elif node.op == FilterOp.IN:
                if not isinstance(value, list) or not value:
                    raise BadRequestException("IN value must be a non-empty list.")
                converted: list[MedicalConditionStatus] = []
                for item in value:
                    if not isinstance(item, str):
                        raise BadRequestException("condition_status IN values must be strings.")
                    try:
                        converted.append(MedicalConditionStatus(item.lower()))
                    except ValueError:
                        raise BadRequestException("Invalid condition_status.")
                value = converted

            else:
                raise BadRequestException("condition_status only supports eq or in.")

        if node.field == PetMedicalConditionFilterField.DIAGNOSIS_DATE:
            if node.op not in {FilterOp.EQ, FilterOp.GTE, FilterOp.LTE}:
                raise BadRequestException("diagnosis_date only supports eq, gte, or lte.")
            value = _parse_iso_date(value)

        if node.field == PetMedicalConditionFilterField.CONDITION_NAME:
            if node.op not in {FilterOp.EQ, FilterOp.ILIKE, FilterOp.IN}:
                raise BadRequestException("condition_name only supports eq, ilike, or in.")

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


@router.post("/{username}/pet/{pet_id}/medical_condition", response_model=PetMedicalConditionRead, status_code=201)
async def write_pet_medical_condition(
    request: Request,
    username: str,
    pet_id: int,
    medical_condition: PetMedicalConditionCreate,
    # current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> PetMedicalConditionRead:
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

    # if current_user.id != db_user_id:
    #     raise ForbiddenException()

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

    pet_medical_condition_model = PetMedicalCondition(**medical_condition.model_dump(), pet_id=db_pet_id)
    db.add(pet_medical_condition_model)

    try:
        await db.commit()

    except IntegrityError as error:
        await db.rollback()

        if "uq_pet_medical_condition_pet_id_condition_name_active" in str(getattr(error, "orig", "")):
            raise BadRequestException("This condition already exists for this pet.")

        raise BadRequestException("Unable to create the medical condition. Please try again.")

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the pet medical condition. Please try again later."
        )

    await db.refresh(pet_medical_condition_model)

    return PetMedicalConditionRead.model_validate(pet_medical_condition_model)


@router.post(
    "/{username}/pet/{pet_id}/medical_conditions/search",
    response_model=PaginatedListResponse[PetMedicalConditionRead]
)
async def search_pet_medical_conditions(
    request: Request,
    username: str,
    pet_id: int,
    values: PetMedicalConditionSearchRequest,
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
        PetMedicalConditionFilterField.CONDITION_NAME: PetMedicalCondition.condition_name,
        PetMedicalConditionFilterField.SEVERITY_LEVEL: PetMedicalCondition.severity_level,
        PetMedicalConditionFilterField.CONDITION_STATUS: PetMedicalCondition.condition_status,
        PetMedicalConditionFilterField.DIAGNOSIS_DATE: PetMedicalCondition.diagnosis_date,
    }

    sort_columns = {
        PetMedicalConditionSortBy.CONDITION_NAME: PetMedicalCondition.condition_name,
        PetMedicalConditionSortBy.SEVERITY_LEVEL: PetMedicalCondition.severity_level,
        PetMedicalConditionSortBy.CONDITION_STATUS: PetMedicalCondition.condition_status,
        PetMedicalConditionSortBy.DIAGNOSIS_DATE: PetMedicalCondition.diagnosis_date,
        PetMedicalConditionSortBy.CREATED_AT: PetMedicalCondition.created_at,
    }

    where_clauses = [
        PetMedicalCondition.pet_id == db_pet_id,
        ~PetMedicalCondition.is_deleted
    ]

    if values.where is not None:
        where_clauses.append(build_where(values.where, filter_columns))

    sort_column = sort_columns.get(values.sort_by)
    if not sort_column:
        raise BadRequestException("Invalid sort_by field.")

    order_by_clause = sort_column.asc() if values.sort_order == SortOrder.ASC else sort_column.desc()

    db_pet_medical_conditions = (
        await db.execute(
            select(PetMedicalCondition)
            .where(*where_clauses)
            .order_by(order_by_clause)
            .offset(compute_offset(values.page, values.items_per_page))
            .limit(values.items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(PetMedicalCondition)
            .where(*where_clauses)
        )
    ).scalar_one()

    pet_medical_conditions_data = {
        "data": [PetMedicalConditionRead.model_validate(item) for item in db_pet_medical_conditions],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(
        crud_data=pet_medical_conditions_data,
        page=values.page,
        items_per_page=values.items_per_page
    )
    return response


@router.get(
    "/{username}/pet/{pet_id}/medical_conditions",
    response_model=PaginatedListResponse[PetMedicalConditionRead]
)
@cache(
    key_prefix="{username}_pet_{pet_id}_medical_conditions:page_{page}:items_per_page:{items_per_page}",
    resource_id_name="pet_id",
    expiration=60,
)
async def read_pet_medical_conditions(
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

    db_pet_medical_conditions = (
        await db.execute(
            select(PetMedicalCondition)
            .where(
                PetMedicalCondition.pet_id == db_pet_id,
                ~PetMedicalCondition.is_deleted
            )
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(PetMedicalCondition)
            .where(
                PetMedicalCondition.pet_id == db_pet_id,
                ~PetMedicalCondition.is_deleted
            )
        )
    ).scalar_one()

    pet_medical_conditions_data = {
        "data": [PetMedicalConditionRead.model_validate(item) for item in db_pet_medical_conditions],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(
        crud_data=pet_medical_conditions_data,
        page=page,
        items_per_page=items_per_page
    )
    return response


@router.get("/{username}/pet/{pet_id}/medical_condition/{id}", response_model=PetMedicalConditionRead)
@cache(key_prefix="{username}_pet_{pet_id}_medical_condition_cache", resource_id_name="id")
async def read_pet_medical_condition(
    request: Request,
    username: str,
    pet_id: int,
    id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> PetMedicalConditionRead:
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

    db_pet_medical_condition = (
        await db.execute(
            select(PetMedicalCondition)
            .where(
                PetMedicalCondition.id == id,
                PetMedicalCondition.pet_id == db_pet_id,
                ~PetMedicalCondition.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_medical_condition:
        raise NotFoundException("Pet medical condition not found")

    return PetMedicalConditionRead.model_validate(db_pet_medical_condition)


@router.patch("/{username}/pet/{pet_id}/medical_condition/{id}")
@cache(
    "{username}_pet_{pet_id}_medical_condition_cache",
    resource_id_name="id",
    pattern_to_invalidate_extra=["{username}_pet_{pet_id}_medical_conditions:*"],
)
async def patch_pet_medical_condition(
    request: Request,
    username: str,
    pet_id: int,
    id: int,
    values: PetMedicalConditionUpdate,
    # current_user: Annotated[UserRead, Depends(get_authenticated_user)],
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

    # if current_user.id != db_user_id:
    #     raise ForbiddenException()

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

    db_pet_medical_condition = (
        await db.execute(
            select(PetMedicalCondition)
            .where(
                PetMedicalCondition.id == id,
                PetMedicalCondition.pet_id == db_pet_id,
                ~PetMedicalCondition.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_medical_condition:
        raise NotFoundException("Pet medical condition not found")

    for field, value in values.model_dump(exclude_unset=True).items():
        setattr(db_pet_medical_condition, field, value)

    db_pet_medical_condition.updated_at = datetime.now(UTC)

    try:
        await db.commit()

    except IntegrityError as error:
        await db.rollback()

        if "uq_pet_medical_condition_pet_id_condition_name_active" in str(getattr(error, "orig", "")):
            raise BadRequestException("This condition already exists for this pet.")

        raise BadRequestException("Unable to update the medical condition. Please try again.")

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the pet medical condition. Please try again later."
        )

    return {"message": "Pet medical condition updated"}


@router.delete("/{username}/pet/{pet_id}/medical_condition/{id}")
@cache(
    "{username}_pet_{pet_id}_medical_condition_cache",
    resource_id_name="id",
    to_invalidate_extra={"{username}_pet_{pet_id}_medical_conditions": "{pet_id}"},
)
async def erase_pet_medical_condition(
    request: Request,
    username: str,
    pet_id: int,
    id: int,
    # current_user: Annotated[UserRead, Depends(get_authenticated_user)],
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

    # if current_user.id != db_user_id:
    #     raise ForbiddenException()

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

    db_pet_medical_condition = (
        await db.execute(
            select(PetMedicalCondition)
            .where(
                PetMedicalCondition.id == id,
                PetMedicalCondition.pet_id == db_pet_id,
                ~PetMedicalCondition.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_medical_condition:
        raise NotFoundException("Pet medical condition not found")

    now = datetime.now(UTC)
    db_pet_medical_condition.is_deleted = True
    db_pet_medical_condition.deleted_at = now
    db.add(db_pet_medical_condition)

    try:
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the pet medical condition. Please try again later."
        )

    return {"message": "Pet medical condition deleted"}


@router.delete(
    "/{username}/pet/{pet_id}/db_pet_medical_condition/{id}",
    dependencies=[Depends(get_authenticated_superuser)]
)
@cache(
    "{username}_pet_{pet_id}_medical_condition_cache",
    resource_id_name="id",
    to_invalidate_extra={"{username}_pet_{pet_id}_medical_conditions": "{pet_id}"},
)
async def erase_db_pet_medical_condition(
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

    db_pet_medical_condition = (
        await db.execute(
            select(PetMedicalCondition)
            .where(
                PetMedicalCondition.id == id,
                PetMedicalCondition.pet_id == db_pet_id,
                ~PetMedicalCondition.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_medical_condition:
        raise NotFoundException("Pet medical condition not found")

    try:
        await db.delete(db_pet_medical_condition)
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the pet medical condition. Please try again later."
        )

    return {"message": "Pet medical condition deleted from the database"}
