import logging
from datetime import UTC, datetime
from enum import Enum
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
from ...models.pet_schedule import PetSchedule, PetScheduleType
from ...models.user import User
from ...schemas.pet_schedule import PetScheduleCreate, PetScheduleRead, PetScheduleUpdate
from ...schemas.user import UserRead

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["pet_schedules"])


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class PetScheduleSortBy(str, Enum):
    TYPE = "type"
    TITLE = "title"
    SCHEDULED_AT = "scheduled_at"
    CREATED_AT = "created_at"


class FilterOp(str, Enum):
    EQ = "eq"
    ILIKE = "ilike"
    GTE = "gte"
    LTE = "lte"
    IN = "in"


class PetScheduleFilterField(str, Enum):
    TYPE = "type"
    TITLE = "title"
    SCHEDULED_AT = "scheduled_at"


class WhereRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["rule"]
    field: PetScheduleFilterField
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


class PetScheduleSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1)
    items_per_page: int = Field(10, ge=1, le=100)

    sort_by: PetScheduleSortBy = PetScheduleSortBy.SCHEDULED_AT
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


def _parse_iso_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value

    if not isinstance(value, str):
        raise BadRequestException("Datetime filter value must be an ISO datetime string.")

    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise BadRequestException("Invalid datetime format. Use ISO format (e.g. 2026-01-26T10:30:00+00:00).")


def build_where(node: WhereNode, filter_columns: dict[PetScheduleFilterField, Any]):  # noqa: C901
    if isinstance(node, WhereRule):
        column = filter_columns[node.field]
        value = node.value

        if node.field == PetScheduleFilterField.TYPE:
            if node.op == FilterOp.EQ:
                if isinstance(value, str):
                    try:
                        value = PetScheduleType(value.lower())
                    except ValueError:
                        raise BadRequestException("Invalid type.")
                if not isinstance(value, PetScheduleType):
                    raise BadRequestException("Invalid type.")

            elif node.op == FilterOp.IN:
                if not isinstance(value, list) or not value:
                    raise BadRequestException("IN value must be a non-empty list.")
                converted: list[PetScheduleType] = []
                for item in value:
                    if not isinstance(item, str):
                        raise BadRequestException("type IN values must be strings.")
                    try:
                        converted.append(PetScheduleType(item.lower()))
                    except ValueError:
                        raise BadRequestException("Invalid type.")
                value = converted

            else:
                raise BadRequestException("type only supports eq or in.")

        if node.field == PetScheduleFilterField.SCHEDULED_AT:
            if node.op not in {FilterOp.EQ, FilterOp.GTE, FilterOp.LTE}:
                raise BadRequestException("scheduled_at only supports eq, gte, or lte.")
            value = _parse_iso_datetime(value)

        if node.field == PetScheduleFilterField.TITLE:
            if node.op not in {FilterOp.EQ, FilterOp.ILIKE, FilterOp.IN}:
                raise BadRequestException("title only supports eq, ilike, or in.")

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


@router.post("/{username}/pet/{pet_id}/schedule", response_model=PetScheduleRead, status_code=201)
async def write_pet_schedule(
    request: Request,
    username: str,
    pet_id: int,
    schedule: PetScheduleCreate,
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> PetScheduleRead:
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

    payload = schedule.model_dump()
    payload["next_scheduled_at"] = payload["scheduled_at"]

    pet_schedule_model = PetSchedule(**payload, pet_id=db_pet_id)
    db.add(pet_schedule_model)

    try:
        await db.commit()

    except IntegrityError as error:
        await db.rollback()

        if "uq_pet_schedule_pet_id_title_active" in str(getattr(error, "orig", "")):
            raise BadRequestException("This schedule title already exists for this pet.")

        raise BadRequestException("Unable to create the schedule. Please try again.")

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the pet schedule. Please try again later."
        )

    await db.refresh(pet_schedule_model)

    return PetScheduleRead.model_validate(pet_schedule_model)


@router.post(
    "/{username}/pet/{pet_id}/schedules/search",
    response_model=PaginatedListResponse[PetScheduleRead]
)
async def search_pet_schedules(
    request: Request,
    username: str,
    pet_id: int,
    values: PetScheduleSearchRequest,
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
        PetScheduleFilterField.TYPE: PetSchedule.type,
        PetScheduleFilterField.TITLE: PetSchedule.title,
        PetScheduleFilterField.SCHEDULED_AT: PetSchedule.scheduled_at,
    }

    sort_columns = {
        PetScheduleSortBy.TYPE: PetSchedule.type,
        PetScheduleSortBy.TITLE: PetSchedule.title,
        PetScheduleSortBy.SCHEDULED_AT: PetSchedule.scheduled_at,
        PetScheduleSortBy.CREATED_AT: PetSchedule.created_at,
    }

    where_clauses = [
        PetSchedule.pet_id == db_pet_id,
        ~PetSchedule.is_deleted
    ]

    if values.where is not None:
        where_clauses.append(build_where(values.where, filter_columns))

    sort_column = sort_columns.get(values.sort_by)
    if not sort_column:
        raise BadRequestException("Invalid sort_by field.")

    order_by_clause = sort_column.asc() if values.sort_order == SortOrder.ASC else sort_column.desc()

    db_pet_schedules = (
        await db.execute(
            select(PetSchedule)
            .where(*where_clauses)
            .order_by(order_by_clause)
            .offset(compute_offset(values.page, values.items_per_page))
            .limit(values.items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(PetSchedule)
            .where(*where_clauses)
        )
    ).scalar_one()

    pet_schedules_data = {
        "data": [PetScheduleRead.model_validate(schedule) for schedule in db_pet_schedules],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(
        crud_data=pet_schedules_data,
        page=values.page,
        items_per_page=values.items_per_page
    )
    return response


@router.get("/{username}/pet/{pet_id}/schedules", response_model=PaginatedListResponse[PetScheduleRead])
@cache(
    key_prefix="{username}_pet_{pet_id}_schedules:page_{page}:items_per_page:{items_per_page}",
    resource_id_name="pet_id",
    expiration=60,
)
async def read_pet_schedules(
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

    db_pet_schedules = (
        await db.execute(
            select(PetSchedule)
            .where(
                PetSchedule.pet_id == db_pet_id,
                ~PetSchedule.is_deleted
            )
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(PetSchedule)
            .where(
                PetSchedule.pet_id == db_pet_id,
                ~PetSchedule.is_deleted
            )
        )
    ).scalar_one()

    pet_schedules_data = {
        "data": [PetScheduleRead.model_validate(schedule) for schedule in db_pet_schedules],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(
        crud_data=pet_schedules_data,
        page=page,
        items_per_page=items_per_page
    )
    return response


@router.get("/{username}/pet/{pet_id}/schedule/{id}", response_model=PetScheduleRead)
@cache(key_prefix="{username}_pet_{pet_id}_schedule_cache", resource_id_name="id")
async def read_pet_schedule(
    request: Request,
    username: str,
    pet_id: int,
    id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> PetScheduleRead:
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

    db_pet_schedule = (
        await db.execute(
            select(PetSchedule)
            .where(
                PetSchedule.id == id,
                PetSchedule.pet_id == db_pet_id,
                ~PetSchedule.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_schedule:
        raise NotFoundException("Pet schedule not found")

    return PetScheduleRead.model_validate(db_pet_schedule)


@router.patch("/{username}/pet/{pet_id}/schedule/{id}")
@cache(
    "{username}_pet_{pet_id}_schedule_cache",
    resource_id_name="id",
    pattern_to_invalidate_extra=["{username}_pet_{pet_id}_schedules:*"],
)
async def patch_pet_schedule(
    request: Request,
    username: str,
    pet_id: int,
    id: int,
    values: PetScheduleUpdate,
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

    db_pet_schedule = (
        await db.execute(
            select(PetSchedule)
            .where(
                PetSchedule.id == id,
                PetSchedule.pet_id == db_pet_id,
                ~PetSchedule.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_schedule:
        raise NotFoundException("Pet schedule not found")

    payload = values.model_dump(exclude_unset=True)

    scheduled_at = payload.get("scheduled_at", db_pet_schedule.scheduled_at)
    payload["next_scheduled_at"] = scheduled_at

    for field, value in payload.items():
        setattr(db_pet_schedule, field, value)

    db_pet_schedule.updated_at = datetime.now(UTC)

    try:
        await db.commit()

    except IntegrityError as error:
        await db.rollback()

        if "uq_pet_schedule_pet_id_title_active" in str(getattr(error, "orig", "")):
            raise BadRequestException("This schedule title already exists for this pet.")

        raise BadRequestException("Unable to update the schedule. Please try again.")

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the pet schedule. Please try again later."
        )

    return {"message": "Pet schedule updated"}


@router.delete("/{username}/pet/{pet_id}/schedule/{id}")
@cache(
    "{username}_pet_{pet_id}_schedule_cache",
    resource_id_name="id",
    to_invalidate_extra={"{username}_pet_{pet_id}_schedules": "{pet_id}"},
)
async def erase_pet_schedule(
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

    db_pet_schedule = (
        await db.execute(
            select(PetSchedule)
            .where(
                PetSchedule.id == id,
                PetSchedule.pet_id == db_pet_id,
                ~PetSchedule.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_schedule:
        raise NotFoundException("Pet schedule not found")

    now = datetime.now(UTC)
    db_pet_schedule.is_deleted = True
    db_pet_schedule.deleted_at = now
    db.add(db_pet_schedule)

    try:
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the pet schedule. Please try again later."
        )

    return {"message": "Pet schedule deleted"}


@router.delete(
    "/{username}/pet/{pet_id}/db_pet_schedule/{id}",
    dependencies=[Depends(get_authenticated_superuser)]
)
@cache(
    "{username}_pet_{pet_id}_schedule_cache",
    resource_id_name="id",
    to_invalidate_extra={"{username}_pet_{pet_id}_schedules": "{pet_id}"},
)
async def erase_db_pet_schedule(
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

    db_pet_schedule = (
        await db.execute(
            select(PetSchedule)
            .where(
                PetSchedule.id == id,
                PetSchedule.pet_id == db_pet_id,
                ~PetSchedule.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_schedule:
        raise NotFoundException("Pet schedule not found")

    try:
        await db.delete(db_pet_schedule)
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the pet schedule. Please try again later."
        )

    return {"message": "Pet schedule deleted from the database"}
