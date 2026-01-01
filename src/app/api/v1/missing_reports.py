from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastcrud import PaginatedListResponse, compute_offset, paginated_response
from geoalchemy2.shape import from_shape
from qdrant_client.http.models import UpdateStatus
from shapely.geometry import Point
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...api.dependencies import get_authenticated_user
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from ...core.utils.cache import cache
from ...core.utils.qdrant_cloud import update_payload
from ...models.missing_report import MissingReport
from ...models.pet import Pet
from ...models.user import User
from ...schemas.missing_report import MissingReportCreate, MissingReportRead, MissingReportUpdate
from ...schemas.user import UserRead

router = APIRouter(tags=["missing reports"])


@router.post("/{username}/pet/{pet_id}/missing_report", response_model=MissingReportRead, status_code=201)
async def write_pet(
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
            select(Pet.id)
            .options(selectinload(Pet.profile_images))
            .where(
                Pet.id == pet_id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet:
        raise NotFoundException("Pet not found")

    profile_image_ids = [profile_image.id for profile_image in db_pet.profile_images]

    try:
        result = update_payload(
            collection_name="pet_profile_images",
            point_ids=profile_image_ids,
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
        await db.refresh(missing_report_model)

    except SQLAlchemyError as error:
        await db.rollback()

        if isinstance(error, IntegrityError) and "uq_active_missing_report_per_pet" in str(error.orig):
            raise BadRequestException("Failed to create missing report due to integrity constraint.")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the missing report. Please try again later."
        )

    return MissingReportRead.model_validate(missing_report_model)


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
            .where(~MissingReport.is_deleted)
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(MissingReport)
            .where(~MissingReport.is_deleted)
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

    profile_image_ids = [profile_image.id for profile_image in db_missing_report.pet.profile_images]

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
