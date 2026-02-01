import asyncio
import logging
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastcrud import PaginatedListResponse, compute_offset, paginated_response
from geoalchemy2 import Geometry
from geoalchemy2.functions import ST_Distance, ST_GeomFromText, ST_MakeEnvelope, ST_Within
from geoalchemy2.shape import from_shape
from qdrant_client.http.models import FieldCondition, Filter, MatchValue
from shapely.geometry import Point
from sqlalchemy import cast, func, literal, select, union_all, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...api.dependencies import get_authenticated_user
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import BadRequestException, ForbiddenException, NotFoundException
from ...core.utils import queue
from ...core.utils.cache import cache
from ...core.utils.google_cloud_storage import is_objects_exist
from ...core.utils.qdrant_cloud import client, delete_embedding, search_pet
from ...models.missing_report import MissingReport
from ...models.pet import Pet
from ...models.sighting_report import SightingReport
from ...models.sighting_report_image import SightingReportImage
from ...models.user import User
from ...schemas.missing_report import MapViewport, MissingReportRead
from ...schemas.pet import PetRead
from ...schemas.sighting_report import (
    SightingReportCreateWithImages,
    SightingReportRead,
    SightingReportUpdateWithImages,
    SightingReportWithMatches,
)
from ...schemas.user import UserRead

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["sighting reports"])

def normalize_species(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        value = value.value
    return str(value).lower().strip()


@router.post("/{username}/sighting_report", response_model=SightingReportRead, status_code=201)
async def write_sighting_report(
    request: Request,
    username: str,
    sighting_report: SightingReportCreateWithImages,
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> SightingReportRead:
    db_user_id = (
        await db.execute(
            select(User.id).where(
                User.username == username,
                ~User.is_deleted,
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    if current_user.id != db_user_id:
        raise ForbiddenException()

    images = sighting_report.images or []
    object_keys = [image.image_object_key for image in images]

    if object_keys:
        exists_map = await asyncio.to_thread(is_objects_exist, object_keys)
        missing_object_keys = [
            object_key for object_key, exists in exists_map.items() if not exists
        ]
        if missing_object_keys:
            raise BadRequestException(
                "Some attachment files might not have been uploaded. Please upload them and try again."
            )

    geo_point = sighting_report.sighting_location
    wkb_location = from_shape(
        Point(geo_point.longitude, geo_point.latitude),
        srid=4326,
    )

    sighting_report_model = SightingReport(
        **sighting_report.model_dump(exclude={"sighting_location", "images"}),
        sighting_location=wkb_location,
        user_id=db_user_id,
    )
    db.add(sighting_report_model)
    await db.flush()

    image_models: list[SightingReportImage] = []
    for image in images:
        image_model = SightingReportImage(
            **image.model_dump(),
            sighting_report_id=sighting_report_model.id,
        )
        db.add(image_model)
        image_models.append(image_model)

    await db.flush()

    species_value = normalize_species(sighting_report.pet_type)

    new_images = [
        {
            "id": str(image.uuid),
            "image_object_key": image.image_object_key,
            "payload": {
                "sighting_report_id": str(sighting_report_model.uuid),
                "species": species_value,
            },
        }
        for image in image_models
    ]

    try:
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the sighting report. Please try again later."
        )

    await db.refresh(sighting_report_model)

    try:
        if new_images:
            await queue.pool.enqueue_job("extract_features_task", new_images, "report_sightings")

    except Exception as error:
        LOGGER.warning(f"Failed to enqueue extract_features_task for pet {sighting_report_model.id}: {error}")

    return SightingReportRead.model_validate(sighting_report_model)


@router.post("/get_nearby_sighting_and_missing_report")
async def get_combined_reports_by_viewport(
    db: Annotated[AsyncSession, Depends(async_get_db)],
    viewport: Annotated[MapViewport, Body(...)],
):
    north = viewport.north
    south = viewport.south
    east = viewport.east
    west = viewport.west
    user_lat = viewport.user_latitude
    user_lon = viewport.user_longitude

    if user_lat is not None and user_lon is not None:
        user_point = ST_GeomFromText(f"SRID=4326;POINT({user_lon} {user_lat})")
    else:
        center_lat = (north + south) / 2
        center_lon = (east + west) / 2
        user_point = ST_GeomFromText(f"SRID=4326;POINT({center_lon} {center_lat})")

    envelope = ST_MakeEnvelope(west, south, east, north, 4326)

    sighting_query = (
        select(
            literal("sighting").label("type"),
            SightingReport.id.label("id"),
            ST_Distance(
                cast(SightingReport.sighting_location, Geometry("POINT", 4326)), user_point
            ).label("distance"),
        )
        .where(
            ~SightingReport.is_deleted,
            ST_Within(
                cast(SightingReport.sighting_location, Geometry("POINT", 4326)), envelope
            ),
        )
    )

    missing_query = (
        select(
            literal("missing").label("type"),
            MissingReport.id.label("id"),
            ST_Distance(
                cast(MissingReport.last_seen_location, Geometry("POINT", 4326)), user_point
            ).label("distance"),
        )
        .where(
            ~MissingReport.is_deleted,
            ST_Within(
                cast(MissingReport.last_seen_location, Geometry("POINT", 4326)), envelope
            ),
        )
    )

    combined_query = union_all(sighting_query, missing_query).order_by("distance")
    results = (await db.execute(combined_query)).all()

    sighting_ids = [row.id for row in results if row.type == "sighting"]
    missing_ids = [row.id for row in results if row.type == "missing"]

    sightings_by_id: dict[int, SightingReport] = {}
    if sighting_ids:
        sighting_rows = await db.execute(
            select(SightingReport)
            .options(
                selectinload(SightingReport.pet).selectinload(Pet.profile_images),
            )
            .where(SightingReport.id.in_(sighting_ids), ~SightingReport.is_deleted)
        )
        sightings_by_id = {r.id: r for r in sighting_rows.scalars().all()}

    missing_by_id: dict[int, MissingReport] = {}
    if missing_ids:
        missing_rows = await db.execute(
            select(MissingReport)
            .options(
                selectinload(MissingReport.pet).selectinload(Pet.profile_images),
            )
            .where(MissingReport.id.in_(missing_ids), ~MissingReport.is_deleted)
        )
        missing_by_id = {r.id: r for r in missing_rows.scalars().all()}

    combined = []
    for row in results:
        if row.type == "sighting":
            report = sightings_by_id.get(row.id)
            if report is None:
                continue
            combined.append(
                {
                    "type": "sighting",
                    "distance": float(row.distance),
                    "data": SightingReportRead.model_validate(report, from_attributes=True),
                }
            )
        else:
            report = missing_by_id.get(row.id)
            if report is None:
                continue
            combined.append(
                {
                    "type": "missing",
                    "distance": float(row.distance),
                    "data": MissingReportRead.model_validate(report, from_attributes=True),
                }
            )

    return combined


@router.get("/sighting_reports", response_model=PaginatedListResponse[SightingReportRead])
async def read_all_sighting_reports(
    request: Request,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    page: int = 1,
    items_per_page: int = 10,
) -> dict[str, Any]:
    sighting_reports = (
        await db.execute(
            select(SightingReport)
            .options(selectinload(SightingReport.images))
            .where(~SightingReport.is_deleted)
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(SightingReport)
            .where(~SightingReport.is_deleted)
        )
    ).scalar_one()

    sighting_reports_data = {
        "data": [SightingReportRead.model_validate(sighting_report) for sighting_report in sighting_reports],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(
        crud_data=sighting_reports_data,
        page=page,
        items_per_page=items_per_page
    )
    return response


@router.get("/{username}/sighting_reports", response_model=PaginatedListResponse[SightingReportRead])
@cache(
    key_prefix="{username}_sighting_reports:page_{page}:items_per_page:{items_per_page}",
    resource_id_name="username",
    expiration=60,
)
async def read_sighting_reports(
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

    sighting_reports = (
        await db.execute(
            select(SightingReport)
            .options(selectinload(SightingReport.images))
            .where(
                SightingReport.user_id == db_user_id,
                ~SightingReport.is_deleted
            )
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(SightingReport)
            .where(
                SightingReport.user_id == db_user_id,
                ~SightingReport.is_deleted
            )
        )
    ).scalar_one()

    sighting_reports_data = {
        "data": [SightingReportRead.model_validate(sighting_report) for sighting_report in sighting_reports],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(
        crud_data=sighting_reports_data,
        page=page,
        items_per_page=items_per_page
    )
    return response


@router.get("/{username}/sighting_report/{id}", response_model=SightingReportWithMatches)
async def read_sighting_report(
    request: Request,
    username: str,
    id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> SightingReportWithMatches:
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

    db_sighting_report = (
        await db.execute(
            select(SightingReport)
            .options(selectinload(SightingReport.images))
            .where(
                SightingReport.id == id,
                SightingReport.user_id == db_user_id,
                ~SightingReport.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_sighting_report:
        raise NotFoundException("Sighting report not found")

    image_uuids = [str(img.uuid) for img in db_sighting_report.images]
    if not image_uuids:
        return SightingReportWithMatches.model_validate(db_sighting_report)

    points = client.retrieve(
        collection_name="report_sightings",
        ids=image_uuids,
        with_vectors=True,
    )

    if not points:
        return SightingReportWithMatches.model_validate(db_sighting_report)

    matched_pets = []
    for point in points:
        embedding = point.vector
        results = await asyncio.to_thread(
            search_pet,
            collection_name="pet_profile_images",
            query_vector=embedding,
            limit=25,
            score_threshold=0.60,
            query_filter=Filter(
                must=[FieldCondition(key="is_missing", match=MatchValue(value=True))]
            ),
        )
        for r in results:
            matched_pets.append({
                "report_image_uuid": point.id,
                "matched_pet_id": r["payload"]["pet_id"],
                "score": r["score"],
                "payload": r["payload"],
            })

    unique_pets = {}
    for match in sorted(matched_pets, key=lambda m: m["score"], reverse=True):
        pet_id = match["matched_pet_id"]
        if pet_id not in unique_pets:
            unique_pets[pet_id] = match
        if len(unique_pets) == 10:
            break

    pet_ids = [m["matched_pet_id"] for m in unique_pets.values()]
    if pet_ids:
        pet_uuids = [UUID(str(x)) for x in pet_ids]
        pets_with_profile_images = (
            await db.execute(
                select(Pet)
                .options(selectinload(Pet.profile_images))
                .where(Pet.uuid.in_(pet_uuids), ~Pet.is_deleted)
            )
        ).scalars().all()
    else:
        pets_with_profile_images = []

    pets_map = {str(p.uuid): p for p in pets_with_profile_images}
    for match in unique_pets.values():
        pet = pets_map.get(str(match["matched_pet_id"]))
        if pet:
            match["pet"] = PetRead.model_validate(pet).model_dump()

    report_data = SightingReportRead.model_validate(db_sighting_report).model_dump()
    report_data["matches"] = list(unique_pets.values())
    return SightingReportWithMatches(**report_data)


@router.patch("/{username}/sighting_report/{id}")
@cache(
    "{username}_sighting_report_cache",
    resource_id_name="id",
    pattern_to_invalidate_extra=["{username}_sighting_reports:*"],
)
async def patch_sighting_report(
    request: Request,
    username: str,
    id: int,
    values: SightingReportUpdateWithImages,
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    db_user_id = (
        await db.execute(
            select(User.id).where(
                User.username == username,
                ~User.is_deleted,
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    if current_user.id != db_user_id:
        raise ForbiddenException()

    db_sighting_report = (
        await db.execute(
            select(SightingReport)
            .options(selectinload(SightingReport.images))
            .where(
                SightingReport.id == id,
                SightingReport.user_id == db_user_id,
                ~SightingReport.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_sighting_report:
        raise NotFoundException("Sighting report not found")

    for field, value in values.model_dump(exclude_unset=True, exclude={"images"}).items():
        setattr(db_sighting_report, field, value)

    object_keys = [
        image.image_object_key
        for image in values.images
        if getattr(image, "image_object_key", None) is not None
    ] if values.images else []

    if object_keys:
        exists_map = await asyncio.to_thread(is_objects_exist, object_keys)
        missing_object_keys = [k for k, exists in exists_map.items() if not exists]
        if missing_object_keys:
            raise BadRequestException(
                "Some image files might not have been uploaded. Please upload them and try again."
            )

    existing_images = {image.id: image for image in db_sighting_report.images}

    deleted_image_uuids: list[str] = []
    new_image_models: list[SightingReportImage] = []
    new_images_payload: list[dict[str, Any]] = []

    if values.images is not None:
        image_ids = {
            image.id
            for image in values.images
            if getattr(image, "id", None) is not None
        }

        invalid_ids = image_ids - set(existing_images.keys())
        if invalid_ids:
            raise NotFoundException("Some sighting report images do not exist.")

        deleted_image_ids = list(set(existing_images) - image_ids)
        deleted_image_uuids = [str(existing_images[image_id].uuid) for image_id in deleted_image_ids]

        now = datetime.now(UTC)
        for image_id in deleted_image_ids:
            image = existing_images[image_id]
            image.is_deleted = True
            image.deleted_at = now

        for image in values.images:
            if getattr(image, "id", None) is not None:
                existing_image = existing_images[image.id]
                existing_image.sort_order = image.sort_order

            elif getattr(image, "image_object_key", None) is not None:
                new_image = SightingReportImage(
                    sighting_report_id=db_sighting_report.id,
                    image_object_key=image.image_object_key,
                    sort_order=image.sort_order
                )
                db.add(new_image)
                db_sighting_report.images.append(new_image)
                new_image_models.append(new_image)

        await db.flush()

        if new_image_models:
            species_value = normalize_species(db_sighting_report.pet_type)

            new_images_payload = [
                {
                    "id": str(image.uuid),
                    "image_object_key": image.image_object_key,
                    "payload": {
                        "sighting_report_id": str(db_sighting_report.uuid),
                        "species": species_value,
                    },
                }
                for image in new_image_models
            ]

    db_sighting_report.updated_at = datetime.now(UTC)
    db.add(db_sighting_report)

    try:
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the sighting report. Please try again later.",
        )

    if deleted_image_uuids:
        try:
            await asyncio.to_thread(delete_embedding, "report_sightings", deleted_image_uuids)
        except Exception as error:
            LOGGER.warning(
                f"Failed to delete embeddings for report_sightings {deleted_image_uuids}: {error}"
            )

    if new_images_payload:
        try:
            await queue.pool.enqueue_job("extract_features_task", new_images_payload, "report_sightings")
        except Exception as error:
            LOGGER.warning(f"Failed to enqueue feature extraction job: {error}")

    return {"message": "Sighting report updated"}


@router.delete("/{username}/sighting_report/{id}")
@cache(
    "{username}_sighting_report_cache",
    resource_id_name="id",
    to_invalidate_extra={"{username}_sighting_reports": "{username}"}
)
async def erase_sighting_report(
    request: Request,
    username: str,
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

    sighting_report = (
        await db.execute(
            select(SightingReport)
            .options(selectinload(SightingReport.images))
            .where(
                SightingReport.id == id,
                SightingReport.user_id == db_user_id,
                ~SightingReport.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not sighting_report:
        raise NotFoundException("Sighting report not found")

    image_uuids = [str(image.uuid) for image in sighting_report.images]

    now = datetime.now(UTC)
    sighting_report.is_deleted = True
    sighting_report.deleted_at = now
    db.add(sighting_report)

    try:
        await db.execute(
            update(SightingReportImage)
            .where(
                SightingReportImage.sighting_report_id == sighting_report.id,
                ~SightingReportImage.is_deleted
            )
            .values(
                is_deleted=True,
                deleted_at=now
            )
        )

        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the sighting report. Please try again later."
        )

    if image_uuids:
        try:
            await asyncio.to_thread(delete_embedding, "report_sightings", image_uuids)
        except Exception as error:
            LOGGER.warning(f"Failed to delete embeddings for report_sightings {image_uuids}: {error}")

    return {"message": "Sighting report deleted"}
