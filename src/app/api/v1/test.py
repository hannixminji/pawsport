import asyncio
import logging
from typing import Annotated, Any

from argon2 import PasswordHasher
from fastapi import APIRouter, Depends, HTTPException, Request, status
from geoalchemy2 import Geography, Geometry
from geoalchemy2.shape import from_shape
from pydantic import BaseModel, Field
from shapely.geometry import Point
from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import (
    BadRequestException,
    DuplicateValueException,
    NotFoundException,
)
from ...core.utils import queue
from ...core.utils.google_cloud_storage import is_objects_exist
from ...core.utils.qr_code import generate_qr_and_upload_gcs
from ...models.notification_preference import NotificationPreference
from ...models.pet import Pet
from ...models.pet_allergy import PetAllergy
from ...models.pet_medical_condition import PetMedicalCondition
from ...models.pet_profile_image import PetProfileImage
from ...models.user import User
from ...schemas.pet import PetCreateWithProfileImages, PetRead
from ...schemas.pet_allergy import PetAllergyCreate, PetAllergyRead
from ...schemas.pet_medical_condition import (
    PetMedicalConditionCreate,
    PetMedicalConditionRead,
)
from ...schemas.user import UserCreate, UserRead

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/test", tags=["tests"])

ph = PasswordHasher()


def normalize_species(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        value = value.value
    return str(value).lower().strip()


class NotificationPreferenceUpsert(BaseModel):
    feature: str = Field(..., max_length=64)
    is_enabled: bool


@router.put(
    "/{username}/alert_center",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def set_user_alert_center(
    username: str,
    values: dict[str, float],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> None:
    db_user = (
        await db.execute(
            select(User).where(
                User.username == username,
                ~User.is_deleted,
            )
        )
    ).scalar_one_or_none()
    if not db_user:
        raise NotFoundException("User not found")

    latitude = values.get("latitude")
    longitude = values.get("longitude")
    if latitude is None or longitude is None:
        raise NotFoundException("latitude and longitude are required")

    geometry_point = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326)
    geography_point: Any = cast(geometry_point, Geography(geometry_type="POINT", srid=4326))

    try:
        db_user.alert_center_geog = geography_point
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise

@router.get(
    "/{username}",
    status_code=status.HTTP_200_OK,
)
async def read_user_by_username(
    request: Request,
    username: str,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, Any]:
    row = (
        await db.execute(
            select(
                User.id,
                User.username,
                User.hashed_password,
                User.is_deleted,
                User.created_at,
                User.updated_at,
                func.ST_X(cast(User.alert_center_geog, Geometry())).label("alert_center_longitude"),
                func.ST_Y(cast(User.alert_center_geog, Geometry())).label("alert_center_latitude"),
            ).where(
                User.username == username,
                ~User.is_deleted,
            )
        )
    ).first()
    if not row:
        raise NotFoundException("User not found")

    return {
        "id": row.id,
        "username": row.username,
        "is_deleted": bool(row.is_deleted),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "alert_center_longitude": row.alert_center_longitude,
        "alert_center_latitude": row.alert_center_latitude,
    }

@router.post("/user/{username}/notification_preference/upsert")
async def upsert_notification_preference(
    username: str,
    payload: NotificationPreferenceUpsert,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, Any]:
    user_id = (
        await db.execute(
            select(User.id).where(
                User.username == username,
                ~User.is_deleted,
            )
        )
    ).scalar_one_or_none()

    if not user_id:
        raise NotFoundException("User not found")

    now = func.now()

    stmt = (
        insert(NotificationPreference)
        .values(
            user_id=user_id,
            feature=payload.feature,
            is_enabled=payload.is_enabled,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=[
                NotificationPreference.user_id,
                NotificationPreference.feature,
            ],
            set_={
                "is_enabled": payload.is_enabled,
                "updated_at": now,
            },
        )
        .returning(
            NotificationPreference.id,
            NotificationPreference.user_id,
            NotificationPreference.feature,
            NotificationPreference.is_enabled,
            NotificationPreference.created_at,
            NotificationPreference.updated_at,
        )
    )

    try:
        row = (await db.execute(stmt)).mappings().one()
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise BadRequestException(
            f"Upsert failed (maybe missing UNIQUE(user_id, feature)?): {str(getattr(e, 'orig', e))}"
        )
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error while upserting notification preference.",
        )

    return {"ok": True, "preference": dict(row)}


@router.post("/user", response_model=UserRead)
async def create_test_user(
    user: UserCreate,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> UserRead:
    user_data = user.model_dump()
    password = user_data.pop("password", None)

    if password:
        user_data["hashed_password"] = ph.hash(password)

    new_user = User(**user_data)

    internal_alert_center_longitude = 121.0244
    internal_alert_center_latitude = 14.5547
    new_user.alert_center_geog = from_shape(
        Point(internal_alert_center_longitude, internal_alert_center_latitude),
        srid=4326,
    )

    db.add(new_user)

    try:
        await db.flush()

        db.add(
            NotificationPreference(
                user_id=new_user.id,
                feature="nearby_report_alerts",
                is_enabled=True,
            )
        )

        await db.commit()
        await db.refresh(new_user)

    except IntegrityError as error:
        await db.rollback()

        detail = str(getattr(error, "orig", error))
        if "uq_user_email_not_deleted" in detail:
            field = "email"
        elif "uq_user_username_not_deleted" in detail:
            field = "username"
        elif "uq_user_phone_not_deleted" in detail:
            field = "phone number"
        else:
            field = "unknown field"

        raise DuplicateValueException(f"{field} already exists")

    return new_user


@router.post("/{username}/pet", response_model=PetRead, status_code=201)
async def write_pet(
    username: str,
    pet: PetCreateWithProfileImages,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> PetRead:
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

    object_keys = [profile_image.image_object_key for profile_image in pet.profile_images] if pet.profile_images else []
    exists_map = await asyncio.to_thread(is_objects_exist, object_keys)
    missing_object_keys = [object_key for object_key, exists in exists_map.items() if not exists]
    if missing_object_keys:
        raise BadRequestException("Some image files might not have been uploaded. Please upload them and try again.")

    pet_model = Pet(**pet.model_dump(exclude={"profile_images"}), owner_id=db_user_id)
    db.add(pet_model)
    await db.flush()

    qr_object_key = generate_qr_and_upload_gcs(
        data=f"http://localhost:8000/api/v1/pet/qr/{pet_model.uuid}",
        object_key=f"qr_codes/{pet_model.uuid}.png",
        scale=10,
        error="H",
        kind="png"
    )
    pet_model.qr_code_image_object_key = qr_object_key

    profile_image_models = []
    for profile_image in pet.profile_images:
        profile_image_model = PetProfileImage(**profile_image.model_dump(), pet_id=pet_model.id)
        db.add(profile_image_model)
        profile_image_models.append(profile_image_model)

    await db.flush()

    species_value = normalize_species(pet_model.type)

    new_profile_images = [
        {
            "id": str(profile_image.uuid),
            "image_object_key": profile_image.image_object_key,
            "payload": {
                "pet_id": pet_model.id,
                "species": species_value,
                "is_missing": False
            }
        }
        for profile_image in profile_image_models
    ]

    try:
        await db.commit()
    except SQLAlchemyError as error:
        await db.rollback()

        if isinstance(error, IntegrityError) and "uq_pet_primary_image" in str(error.orig):
            raise BadRequestException("A pet can only have one primary profile image.")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the pet. Please try again later."
        )

    try:
        await queue.pool.enqueue_job("extract_features_task", new_profile_images)
    except Exception as error:
        LOGGER.warning(f"Failed to enqueue extract_features_task for pet {pet_model.id}: {error}")

    await db.refresh(pet_model)

    return PetRead.model_validate(pet_model)


@router.get("/debug/due_schedules")
async def debug_due_schedules(
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, Any]:
    from datetime import UTC, datetime

    from sqlalchemy import select

    from ...models.pet import Pet
    from ...models.pet_schedule import PetSchedule

    now = datetime.now(UTC)

    rows = (
        await db.execute(
            select(PetSchedule, Pet.owner_id)
            .join(Pet, Pet.id == PetSchedule.pet_id)
            .where(
                ~Pet.is_deleted,
                ~PetSchedule.is_deleted,
                PetSchedule.next_scheduled_at.is_not(None),
                PetSchedule.next_scheduled_at <= now,
            )
        )
    ).all()

    data = [
        {
            "schedule_id": schedule.id,
            "pet_id": schedule.pet_id,
            "owner_id": owner_id,
            "title": schedule.title,
            "type": getattr(schedule.type, "value", str(schedule.type)),
            "scheduled_at": schedule.scheduled_at.isoformat() if schedule.scheduled_at else None,
            "next_scheduled_at": schedule.next_scheduled_at.isoformat() if schedule.next_scheduled_at else None,
        }
        for schedule, owner_id in rows
    ]

    return {"now": now.isoformat(), "count": len(data), "data": data}


@router.post("/{username}/pet/{pet_id}/allergy", response_model=PetAllergyRead, status_code=201)
async def write_pet_allergy(
    request: Request,
    username: str,
    pet_id: int,
    allergy: PetAllergyCreate,
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


@router.post("/{username}/pet/{pet_id}/medical_condition", response_model=PetMedicalConditionRead, status_code=201)
async def write_pet_medical_condition(
    request: Request,
    username: str,
    pet_id: int,
    medical_condition: PetMedicalConditionCreate,
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
