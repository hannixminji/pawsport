import logging
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Union

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastcrud import PaginatedListResponse, compute_offset, paginated_response
from geoalchemy2.shape import from_shape
from pydantic import BaseModel, ConfigDict, Field, model_validator
from qdrant_client.http.models import UpdateStatus
from shapely.geometry import Point
from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...api.dependencies import get_authenticated_user
from ...core.config import settings
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from ...core.utils import queue
from ...core.utils.cache import cache
from ...core.utils.qdrant_cloud import update_payload
from ...models.missing_report import MissingReport, MissingReportStatus
from ...models.pet import Pet
from ...models.pet_profile_image import PetProfileImage
from ...models.user import User
from ...schemas.missing_report import MissingReportCreate, MissingReportRead, MissingReportUpdate
from ...schemas.user import UserRead

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["missing reports"])


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class MissingReportSortBy(StrEnum):
    LAST_SEEN_DATETIME = "last_seen_datetime"
    CREATED_AT = "created_at"


class FilterOp(StrEnum):
    EQ = "eq"
    ILIKE = "ilike"
    GTE = "gte"
    LTE = "lte"
    IN = "in"


class MissingReportFilterField(StrEnum):
    STATUS = "status"
    LAST_SEEN_DATETIME = "last_seen_datetime"
    CREATED_AT = "created_at"
    LAST_SEEN_ADDRESS = "last_seen_address"
    PET_NAME = "pet_name"
    OWNER_NAME = "owner_name"
    DESCRIPTION = "description"


class WhereRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["rule"]
    field: MissingReportFilterField
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


class MissingReportSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1)
    items_per_page: int = Field(10, ge=1, le=100)

    sort_by: MissingReportSortBy = MissingReportSortBy.CREATED_AT
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
        dt = value

    elif isinstance(value, date) and not isinstance(value, datetime):
        dt = datetime(value.year, value.month, value.day, tzinfo=UTC)

    elif isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"

        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            raise BadRequestException("Datetime filter value must be ISO 8601.")

    else:
        raise BadRequestException("Datetime filter value must be ISO 8601.")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    return dt


def build_where(node: WhereNode, filter_columns: dict[MissingReportFilterField, Any]):  # noqa: C901
    if isinstance(node, WhereRule):
        column = filter_columns[node.field]
        value = node.value

        if node.field == MissingReportFilterField.STATUS:
            if node.op == FilterOp.EQ:
                if isinstance(value, str):
                    try:
                        value = MissingReportStatus(value.lower())
                    except ValueError:
                        raise BadRequestException("Invalid status.")
                if not isinstance(value, MissingReportStatus):
                    raise BadRequestException("Invalid status.")

            elif node.op == FilterOp.IN:
                if not isinstance(value, list) or not value:
                    raise BadRequestException("IN value must be a non-empty list.")
                converted: list[MissingReportStatus] = []
                for item in value:
                    if not isinstance(item, str):
                        raise BadRequestException("status IN values must be strings.")
                    try:
                        converted.append(MissingReportStatus(item.lower()))
                    except ValueError:
                        raise BadRequestException("Invalid status.")
                value = converted

            else:
                raise BadRequestException("status only supports eq or in.")

        if node.field in {
            MissingReportFilterField.LAST_SEEN_DATETIME,
            MissingReportFilterField.CREATED_AT,
        }:
            if node.op not in {FilterOp.EQ, FilterOp.GTE, FilterOp.LTE}:
                raise BadRequestException("datetime fields only support eq, gte, or lte.")
            value = _parse_iso_datetime(value)

        if node.field in {
            MissingReportFilterField.LAST_SEEN_ADDRESS,
            MissingReportFilterField.PET_NAME,
            MissingReportFilterField.OWNER_NAME,
            MissingReportFilterField.DESCRIPTION,
        }:
            if node.op == FilterOp.EQ:
                if not isinstance(value, str):
                    raise BadRequestException("text eq value must be a string.")

            elif node.op == FilterOp.ILIKE:
                if not isinstance(value, str):
                    raise BadRequestException("ILIKE value must be a string.")

            elif node.op == FilterOp.IN:
                if not isinstance(value, list) or not value:
                    raise BadRequestException("IN value must be a non-empty list.")
                if not all(isinstance(item, str) for item in value):
                    raise BadRequestException("text IN values must be strings.")

            else:
                raise BadRequestException("text fields only support eq, ilike, or in.")

        if node.op == FilterOp.EQ:
            return column == value

        if node.op == FilterOp.ILIKE:
            return func.coalesce(column, "").ilike(f"%{value}%")

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


@router.post("/{username}/pet/{pet_id}/missing_report", response_model=MissingReportRead, status_code=201)
async def write_report_missing(
    request: Request,
    username: str,
    pet_id: int,
    missing_report: MissingReportCreate,
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> MissingReportRead:
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

    db_pet = (
        await db.execute(
            select(Pet)
            .where(
                Pet.id == pet_id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted,
            )
        )
    ).scalar_one_or_none()
    if not db_pet:
        raise NotFoundException("Pet not found")

    pet_type = str(db_pet.type).lower().strip() if db_pet.type is not None else ""
    pet_label = pet_type if pet_type in {"dog", "cat"} else "pet"

    geo_point = missing_report.last_seen_location
    wkb_location = from_shape(Point(geo_point.longitude, geo_point.latitude), srid=4326)

    missing_report_model = MissingReport(
        **missing_report.model_dump(exclude={"last_seen_location"}),
        pet_id=pet_id,
        last_seen_location=wkb_location
    )
    db.add(missing_report_model)

    try:
        await db.commit()

    except SQLAlchemyError as error:
        await db.rollback()

        if isinstance(error, IntegrityError) and "uq_active_missing_report_per_pet" in str(error.orig):
            raise BadRequestException("A missing report for this pet already exists.")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the missing report. Please try again later."
        )

    profile_image_uuids = (
        await db.execute(
            select(PetProfileImage.uuid)
            .where(
                PetProfileImage.pet_id == pet_id,
                ~PetProfileImage.is_deleted,
            ).order_by(
                PetProfileImage.sort_order.asc(),
                PetProfileImage.created_at.desc(),
            )
        )
    ).scalars().all()

    profile_image_uuids = [str(uuid) for uuid in profile_image_uuids]

    try:
        if profile_image_uuids:
            result = update_payload(
                collection_name="pet_profile_images",
                point_ids=profile_image_uuids,
                payload={"is_missing": True}
            )

            if result.status != UpdateStatus.COMPLETED:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="An unexpected error occurred while creating the missing report. Please try again later."
                )

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the missing report. Please try again later."
        )

    await db.refresh(missing_report_model)

    try:
        await queue.pool.enqueue_job(
            "notify_nearby_alert_center_task",
            event_longitude=geo_point.longitude,
            event_latitude=geo_point.latitude,
            notification_title="🚨 Missing pet alert",
            notification_body=f"A missing {pet_label} was reported nearby. Tap to view details.",
            notification_data={
                "type": "missing_report_created",
                "pet_id": str(pet_id),
                "missing_report_id": str(missing_report_model.id),
                "pet_type": pet_label,
                "username": current_user.username,
            },
            notification_feature="nearby_report_alerts",
            radius_in_meters=settings.NEARBY_ALERT_CENTER_RADIUS_METERS,
            excluded_user_id=current_user.id,
        )
    except Exception as error:
        LOGGER.warning(f"Failed to enqueue notify_nearby_alert_center_task: {error}")

    return MissingReportRead.model_validate(missing_report_model)


@router.post(
    "/missing_reports/search",
    response_model=PaginatedListResponse[MissingReportRead],
)
async def search_missing_reports(
    request: Request,
    values: MissingReportSearchRequest,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, Any]:
    owner_name_column = (
        getattr(User, "name", None)
        or getattr(User, "full_name", None)
        or getattr(User, "display_name", None)
        or User.username
    )

    filter_columns = {
        MissingReportFilterField.STATUS: MissingReport.status,
        MissingReportFilterField.LAST_SEEN_DATETIME: MissingReport.last_seen_datetime,
        MissingReportFilterField.CREATED_AT: MissingReport.created_at,
        MissingReportFilterField.LAST_SEEN_ADDRESS: MissingReport.last_seen_address,
        MissingReportFilterField.PET_NAME: Pet.name,
        MissingReportFilterField.OWNER_NAME: owner_name_column,
        MissingReportFilterField.DESCRIPTION: MissingReport.description,
    }

    sort_columns = {
        MissingReportSortBy.LAST_SEEN_DATETIME: MissingReport.last_seen_datetime,
        MissingReportSortBy.CREATED_AT: MissingReport.created_at,
    }

    where_clauses = [
        ~MissingReport.is_deleted,
        ~Pet.is_deleted,
        ~User.is_deleted,
    ]

    if values.where is not None:
        where_clauses.append(build_where(values.where, filter_columns))

    sort_column = sort_columns.get(values.sort_by)
    if not sort_column:
        raise BadRequestException("Invalid sort_by field.")

    order_by_clause = sort_column.asc() if values.sort_order == SortOrder.ASC else sort_column.desc()

    db_missing_reports = (
        await db.execute(
            select(MissingReport)
            .options(selectinload(MissingReport.pet).selectinload(Pet.profile_images))
            .join(Pet, Pet.id == MissingReport.pet_id)
            .join(User, User.id == Pet.owner_id)
            .where(*where_clauses)
            .order_by(order_by_clause)
            .offset(compute_offset(values.page, values.items_per_page))
            .limit(values.items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(MissingReport)
            .join(Pet, Pet.id == MissingReport.pet_id)
            .join(User, User.id == Pet.owner_id)
            .where(*where_clauses)
        )
    ).scalar_one()

    missing_reports_data = {
        "data": [MissingReportRead.model_validate(item) for item in db_missing_reports],
        "total_count": total_count,
    }

    response: dict[str, Any] = paginated_response(
        crud_data=missing_reports_data,
        page=values.page,
        items_per_page=values.items_per_page,
    )
    return response


@router.get("/missing_reports", response_model=PaginatedListResponse[MissingReportRead])
async def read_all_missing_reports(
    request: Request,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    page: int = 1,
    items_per_page: int = 10,
) -> dict[str, Any]:
    missing_reports = (
        await db.execute(
            select(MissingReport)
            .options(selectinload(MissingReport.pet).selectinload(Pet.profile_images))
            .join(Pet, Pet.id == MissingReport.pet_id)
            .where(
                ~MissingReport.is_deleted,
                ~Pet.is_deleted
            )
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(MissingReport)
            .join(Pet, Pet.id == MissingReport.pet_id)
            .where(
                ~MissingReport.is_deleted,
                ~Pet.is_deleted,
            )
        )
    ).scalar_one()

    reports_data = {
        "data": [MissingReportRead.model_validate(missing_report) for missing_report in missing_reports],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(crud_data=reports_data, page=page, items_per_page=items_per_page)
    return response


@router.get("/{username}/missing_reports", response_model=PaginatedListResponse[MissingReportRead])
@cache(
    key_prefix="{username}_missing_reports:page_{page}:items_per_page:{items_per_page}",
    resource_id_name="username",
    expiration=60,
)
async def read_missing_reports(
    request: Request,
    username: str,
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

    missing_reports = (
        await db.execute(
            select(MissingReport)
            .options(selectinload(MissingReport.pet).selectinload(Pet.profile_images))
            .join(Pet, Pet.id == MissingReport.pet_id)
            .where(
                Pet.owner_id == db_user_id,
                ~MissingReport.is_deleted
            )
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(MissingReport)
            .join(Pet, Pet.id == MissingReport.pet_id)
            .where(
                Pet.owner_id == db_user_id,
                ~MissingReport.is_deleted
            )
        )
    ).scalar_one()

    missing_reports_data = {
        "data": [MissingReportRead.model_validate(missing_report) for missing_report in missing_reports],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(
        crud_data=missing_reports_data,
        page=page,
        items_per_page=items_per_page,
    )
    return response


@router.get("/{username}/missing_report/{id}", response_model=MissingReportRead)
@cache(key_prefix="{username}_missing_report_cache", resource_id_name="id")
async def read_missing_report(
    request: Request,
    username: str,
    id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> MissingReportRead:
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

    db_missing_report = (
        await db.execute(
            select(MissingReport)
            .options(selectinload(MissingReport.pet).selectinload(Pet.profile_images))
            .join(Pet, Pet.id == MissingReport.pet_id)
            .where(
                MissingReport.id == id,
                Pet.owner_id == db_user_id,
                ~MissingReport.is_deleted
            )
        )
    ).scalar_one_or_none()
    if db_missing_report is None:
        raise NotFoundException("Missing report not found")

    return MissingReportRead.model_validate(db_missing_report)


@router.patch("/{username}/missing_report/{id}")
@cache(
    "{username}_missing_report_cache",
    resource_id_name="id",
    pattern_to_invalidate_extra=["{username}_missing_reports:*"]
)
async def patch_missing_report(
    request: Request,
    username: str,
    id: int,
    values: MissingReportUpdate,
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

    db_missing_report = (
        await db.execute(
            select(MissingReport)
            .options(selectinload(MissingReport.pet).selectinload(Pet.profile_images))
            .join(Pet, Pet.id == MissingReport.pet_id)
            .where(
                MissingReport.id == id,
                Pet.owner_id == db_user_id,
                ~MissingReport.is_deleted
            )
        )
    ).scalar_one_or_none()
    if db_missing_report is None:
        raise NotFoundException("Missing report not found")

    profile_image_ids = [str(profile_image.uuid) for profile_image in db_missing_report.pet.profile_images]

    for field, value in values.model_dump(exclude_unset=True, exclude={"last_seen_location"}).items():
        setattr(db_missing_report, field, value)

    if getattr(values, "last_seen_location", None) is not None:
        geo_point = values.last_seen_location
        wkb_location = from_shape(Point(geo_point.longitude, geo_point.latitude), srid=4326)
        db_missing_report.last_seen_location = wkb_location

    db_missing_report.updated_at = datetime.now(UTC)
    db.add(db_missing_report)

    if db_missing_report.status != "missing":
        try:
            result = update_payload(
                collection_name="pet_profile_images",
                point_ids=profile_image_ids,
                payload={"is_missing": False}
            )

            if result.status != UpdateStatus.COMPLETED:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="An unexpected error occurred while updating the missing report. Please try again later."
                )

        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred while updating the missing report. Please try again later."
            )

    try:
        await db.commit()
        await db.refresh(db_missing_report)

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the missing report. Please try again later."
        )

    return {"message": "Missing report updated"}


@router.delete("/{username}/missing_report/{id}")
@cache(
    "{username}_missing_report_cache",
    resource_id_name="id",
    to_invalidate_extra={"{username}_missing_reports": "{username}"}
)
async def erase_missing_report(
    request: Request,
    username: str,
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

    db_missing_report = (
        await db.execute(
            select(MissingReport)
            .options(selectinload(MissingReport.pet).selectinload(Pet.profile_images))
            .join(Pet, Pet.id == MissingReport.pet_id)
            .where(
                MissingReport.id == id,
                Pet.owner_id == db_user_id,
                ~MissingReport.is_deleted
            )
        )
    ).scalar_one_or_none()
    if db_missing_report is None:
        raise NotFoundException("Missing report not found")

    now = datetime.now(UTC)
    db_missing_report.is_deleted = True
    db_missing_report.deleted_at = now
    db.add(db_missing_report)

    try:
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the missing report. Please try again later."
        )

    return {"message": "Missing report deleted"}
