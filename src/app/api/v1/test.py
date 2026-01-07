import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import (
    BadRequestException,
    DuplicateValueException,
    NotFoundException,
)
from ...core.security import get_password_hash
from ...core.utils import queue
from ...core.utils.google_cloud_storage import is_objects_exist
from ...core.utils.qr_code import generate_qr_and_upload_gcs
from ...models.pet import Pet
from ...models.pet_profile_image import PetProfileImage
from ...models.user import User
from ...schemas.pet import PetCreateWithProfileImages, PetRead
from ...schemas.user import UserCreate, UserRead

router = APIRouter(prefix="/test", tags=["tests"])


@router.post("/user", response_model=UserRead)
async def create_test_user(
    user: UserCreate,
    db: Annotated[AsyncSession, Depends(async_get_db)]
) -> UserRead:
    user_data = user.model_dump()
    password = user_data.pop("password", None)
    if password:
        user_data["hashed_password"] = get_password_hash(password)

    new_user = User(**user_data)
    db.add(new_user)

    try:
        await db.commit()
        await db.refresh(new_user)

    except IntegrityError as error:
        await db.rollback()

        detail = str(error.orig)
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
async def write_test_pet(
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

    object_keys = [profile_image.image_object_key for profile_image in pet.profile_images]
    exists_map = await asyncio.to_thread(is_objects_exist, object_keys)
    missing_object_keys = [object_key for object_key, exists in exists_map.items() if not exists]
    if missing_object_keys:
        raise BadRequestException("Some image files might not have been uploaded. Please upload them and try again.")

    pet_model = Pet(**pet.model_dump(exclude={"profile_images"}), owner_id=db_user_id)
    db.add(pet_model)
    await db.flush()

    qr_object_key = generate_qr_and_upload_gcs(
        data=f"http://localhost/api/v1/pet/qr/{pet_model.uuid}",
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

    new_profile_images = [
        {
            "id": str(profile_image.uuid),
            "image_object_key": profile_image.image_object_key,
            "payload": {
                "pet_id": pet_model.id,
                "type": pet_model.type,
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
    except Exception:
        pass

    await db.refresh(pet_model)

    return PetRead.model_validate(pet_model)
