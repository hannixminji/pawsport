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
from ...models.pet_medication import MedicationFrequency, MedicationRoute, PetMedication
from ...models.user import User
from ...schemas.pet_medication import PetMedicationCreate, PetMedicationRead, PetMedicationUpdate
from ...schemas.user import UserRead

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["pet_medications"])


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class PetMedicationSortBy(StrEnum):
    MEDICATION = "medication"
    FREQUENCY = "frequency"
    ROUTE = "route"
    START_DATE = "start_date"
    END_DATE = "end_date"
    CREATED_AT = "created_at"


class FilterOp(StrEnum):
    EQ = "eq"
    ILIKE = "ilike"
    GTE = "gte"
    LTE = "lte"
    IN = "in"


class PetMedicationFilterField(StrEnum):
    MEDICATION = "medication"
    FREQUENCY = "frequency"
    ROUTE = "route"
    START_DATE = "start_date"
    END_DATE = "end_date"


class WhereRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["rule"]
    field: PetMedicationFilterField
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


class PetMedicationSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1)
    items_per_page: int = Field(10, ge=1, le=100)

    sort_by: PetMedicationSortBy = PetMedicationSortBy.START_DATE
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


def build_where(node: WhereNode, filter_columns: dict[PetMedicationFilterField, Any]):  # noqa: C901
    if isinstance(node, WhereRule):
        column = filter_columns[node.field]
        value = node.value

        if node.field == PetMedicationFilterField.FREQUENCY:
            if node.op == FilterOp.EQ:
                if isinstance(value, str):
                    try:
                        value = MedicationFrequency(value.lower())
                    except ValueError:
                        raise BadRequestException("Invalid frequency.")
                if not isinstance(value, MedicationFrequency):
                    raise BadRequestException("Invalid frequency.")

            elif node.op == FilterOp.IN:
                if not isinstance(value, list) or not value:
                    raise BadRequestException("IN value must be a non-empty list.")
                converted: list[MedicationFrequency] = []
                for item in value:
                    if not isinstance(item, str):
                        raise BadRequestException("frequency IN values must be strings.")
                    try:
                        converted.append(MedicationFrequency(item.lower()))
                    except ValueError:
                        raise BadRequestException("Invalid frequency.")
                value = converted

            else:
                raise BadRequestException("frequency only supports eq or in.")

        if node.field == PetMedicationFilterField.ROUTE:
            if node.op == FilterOp.EQ:
                if isinstance(value, str):
                    try:
                        value = MedicationRoute(value.lower())
                    except ValueError:
                        raise BadRequestException("Invalid route.")
                if not isinstance(value, MedicationRoute):
                    raise BadRequestException("Invalid route.")

            elif node.op == FilterOp.IN:
                if not isinstance(value, list) or not value:
                    raise BadRequestException("IN value must be a non-empty list.")
                converted: list[MedicationRoute] = []
                for item in value:
                    if not isinstance(item, str):
                        raise BadRequestException("route IN values must be strings.")
                    try:
                        converted.append(MedicationRoute(item.lower()))
                    except ValueError:
                        raise BadRequestException("Invalid route.")
                value = converted

            else:
                raise BadRequestException("route only supports eq or in.")

        if node.field in {PetMedicationFilterField.START_DATE, PetMedicationFilterField.END_DATE}:
            if node.op not in {FilterOp.EQ, FilterOp.GTE, FilterOp.LTE}:
                raise BadRequestException("Date fields only support eq, gte, or lte.")
            value = _parse_iso_date(value)

        if node.field == PetMedicationFilterField.MEDICATION:
            if node.op not in {FilterOp.EQ, FilterOp.ILIKE, FilterOp.IN}:
                raise BadRequestException("medication only supports eq, ilike, or in.")

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


@router.post("/{username}/pet/{pet_id}/medication", response_model=PetMedicationRead, status_code=201)
async def write_pet_medication(
    request: Request,
    username: str,
    pet_id: int,
    medication: PetMedicationCreate,
    # current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> PetMedicationRead:
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

    pet_medication_model = PetMedication(**medication.model_dump(), pet_id=db_pet_id)
    db.add(pet_medication_model)

    try:
        await db.commit()

    except IntegrityError as error:
        await db.rollback()

        if "uq_pet_medication_pet_id_medication_name_active" in str(getattr(error, "orig", "")):
            raise BadRequestException("This medication already exists for this pet.")

        raise BadRequestException("Unable to create the medication. Please try again.")

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the pet medication. Please try again later."
        )

    await db.refresh(pet_medication_model)

    return PetMedicationRead.model_validate(pet_medication_model)


@router.post(
    "/{username}/pet/{pet_id}/medications/search",
    response_model=PaginatedListResponse[PetMedicationRead]
)
async def search_pet_medications(
    request: Request,
    username: str,
    pet_id: int,
    values: PetMedicationSearchRequest,
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
        PetMedicationFilterField.MEDICATION: PetMedication.medication,
        PetMedicationFilterField.FREQUENCY: PetMedication.frequency,
        PetMedicationFilterField.ROUTE: PetMedication.route,
        PetMedicationFilterField.START_DATE: PetMedication.start_date,
        PetMedicationFilterField.END_DATE: PetMedication.end_date,
    }

    sort_columns = {
        PetMedicationSortBy.MEDICATION: PetMedication.medication,
        PetMedicationSortBy.FREQUENCY: PetMedication.frequency,
        PetMedicationSortBy.ROUTE: PetMedication.route,
        PetMedicationSortBy.START_DATE: PetMedication.start_date,
        PetMedicationSortBy.END_DATE: PetMedication.end_date,
        PetMedicationSortBy.CREATED_AT: PetMedication.created_at,
    }

    where_clauses = [
        PetMedication.pet_id == db_pet_id,
        ~PetMedication.is_deleted
    ]

    if values.where is not None:
        where_clauses.append(build_where(values.where, filter_columns))

    sort_column = sort_columns.get(values.sort_by)
    if not sort_column:
        raise BadRequestException("Invalid sort_by field.")

    order_by_clause = sort_column.asc() if values.sort_order == SortOrder.ASC else sort_column.desc()

    db_pet_medications = (
        await db.execute(
            select(PetMedication)
            .where(*where_clauses)
            .order_by(order_by_clause)
            .offset(compute_offset(values.page, values.items_per_page))
            .limit(values.items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(PetMedication)
            .where(*where_clauses)
        )
    ).scalar_one()

    pet_medications_data = {
        "data": [PetMedicationRead.model_validate(medication) for medication in db_pet_medications],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(
        crud_data=pet_medications_data,
        page=values.page,
        items_per_page=values.items_per_page
    )
    return response


@router.get("/{username}/pet/{pet_id}/medications", response_model=PaginatedListResponse[PetMedicationRead])
@cache(
    key_prefix="{username}_pet_{pet_id}_medications:page_{page}:items_per_page:{items_per_page}",
    resource_id_name="pet_id",
    expiration=60,
)
async def read_pet_medications(
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

    db_pet_medications = (
        await db.execute(
            select(PetMedication)
            .where(
                PetMedication.pet_id == db_pet_id,
                ~PetMedication.is_deleted
            )
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(PetMedication)
            .where(
                PetMedication.pet_id == db_pet_id,
                ~PetMedication.is_deleted
            )
        )
    ).scalar_one()

    pet_medications_data = {
        "data": [PetMedicationRead.model_validate(medication) for medication in db_pet_medications],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(
        crud_data=pet_medications_data,
        page=page,
        items_per_page=items_per_page
    )
    return response


@router.get("/{username}/pet/{pet_id}/medication/{id}", response_model=PetMedicationRead)
@cache(key_prefix="{username}_pet_{pet_id}_medication_cache", resource_id_name="id")
async def read_pet_medication(
    request: Request,
    username: str,
    pet_id: int,
    id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> PetMedicationRead:
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

    db_pet_medication = (
        await db.execute(
            select(PetMedication)
            .where(
                PetMedication.id == id,
                PetMedication.pet_id == db_pet_id,
                ~PetMedication.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_medication:
        raise NotFoundException("Pet medication not found")

    return PetMedicationRead.model_validate(db_pet_medication)


@router.patch("/{username}/pet/{pet_id}/medication/{id}")
@cache(
    "{username}_pet_{pet_id}_medication_cache",
    resource_id_name="id",
    pattern_to_invalidate_extra=["{username}_pet_{pet_id}_medications:*"],
)
async def patch_pet_medication(
    request: Request,
    username: str,
    pet_id: int,
    id: int,
    values: PetMedicationUpdate,
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

    db_pet_medication = (
        await db.execute(
            select(PetMedication)
            .where(
                PetMedication.id == id,
                PetMedication.pet_id == db_pet_id,
                ~PetMedication.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_medication:
        raise NotFoundException("Pet medication not found")

    payload = values.model_dump(exclude_unset=True)

    start_date = payload.get("start_date", db_pet_medication.start_date)
    end_date = payload.get("end_date", db_pet_medication.end_date)

    if start_date is not None and end_date is not None and end_date < start_date:
        raise BadRequestException("end_date must be on or after start_date")

    for field, value in payload.items():
        setattr(db_pet_medication, field, value)

    db_pet_medication.updated_at = datetime.now(UTC)

    try:
        await db.commit()

    except IntegrityError as error:
        await db.rollback()

        if "uq_pet_medication_pet_id_medication_name_active" in str(getattr(error, "orig", "")):
            raise BadRequestException("This medication already exists for this pet.")

        raise BadRequestException("Unable to update the medication. Please try again.")

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the pet medication. Please try again later."
        )

    return {"message": "Pet medication updated"}


@router.delete("/{username}/pet/{pet_id}/medication/{id}")
@cache(
    "{username}_pet_{pet_id}_medication_cache",
    resource_id_name="id",
    to_invalidate_extra={"{username}_pet_{pet_id}_medications": "{pet_id}"},
)
async def erase_pet_medication(
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

    db_pet_medication = (
        await db.execute(
            select(PetMedication)
            .where(
                PetMedication.id == id,
                PetMedication.pet_id == db_pet_id,
                ~PetMedication.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_medication:
        raise NotFoundException("Pet medication not found")

    now = datetime.now(UTC)
    db_pet_medication.is_deleted = True
    db_pet_medication.deleted_at = now
    db.add(db_pet_medication)

    try:
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the pet medication. Please try again later."
        )

    return {"message": "Pet medication deleted"}


@router.delete(
    "/{username}/pet/{pet_id}/db_pet_medication/{id}",
    dependencies=[Depends(get_authenticated_superuser)]
)
@cache(
    "{username}_pet_{pet_id}_medication_cache",
    resource_id_name="id",
    to_invalidate_extra={"{username}_pet_{pet_id}_medications": "{pet_id}"},
)
async def erase_db_pet_medication(
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

    db_pet_medication = (
        await db.execute(
            select(PetMedication)
            .where(
                PetMedication.id == id,
                PetMedication.pet_id == db_pet_id,
                ~PetMedication.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_medication:
        raise NotFoundException("Pet medication not found")

    try:
        await db.delete(db_pet_medication)
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the pet medication. Please try again later."
        )

    return {"message": "Pet medication deleted from the database"}
