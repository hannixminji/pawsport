import asyncio
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastcrud import PaginatedListResponse, compute_offset, paginated_response
from qdrant_client.http.models import FieldCondition, Filter, MatchValue
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...api.dependencies import get_authenticated_superuser, get_authenticated_user
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import (
    BadRequestException,
    CustomException,
    ForbiddenException,
    NotFoundException,
)
from ...core.utils import queue
from ...core.utils.cache import cache
from ...core.utils.google_cloud_storage import is_objects_exist
from ...core.utils.qdrant_cloud import delete_embedding, search_pet
from ...models.pet import Pet
from ...models.pet_profile_image import PetProfileImage
from ...models.user import User
from ...schemas.pet import PetCreateWithProfileImages, PetRead, PetSearch, PetUpdateWithProfileImages
from ...schemas.user import UserRead

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["pets"])


@router.post("/{username}/pet", response_model=PetRead, status_code=201)
async def write_pet(
    request: Request,
    username: str,
    pet: PetCreateWithProfileImages,
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
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

    if current_user.id != db_user_id:
        raise ForbiddenException()

    object_keys = [profile_image.image_object_key for profile_image in pet.profile_images]
    exists_map = await asyncio.to_thread(is_objects_exist, object_keys)
    missing_object_keys = [object_key for object_key, exists in exists_map.items() if not exists]
    if missing_object_keys:
        raise BadRequestException("Some image files might not have been uploaded. Please upload them and try again.")

    pet_model = Pet(**pet.model_dump(exclude={"profile_images"}), owner_id=db_user_id)
    db.add(pet_model)
    await db.flush()

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
    except Exception as error:
        LOGGER.warning(f"Failed to enqueue extract_features_task for pet {pet_model.id}: {error}")

    await db.refresh(pet_model)

    return PetRead.model_validate(pet_model)


@router.post("/search_pet", response_model=list[PetSearch])
async def search_pets(
    request: Request,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    file: UploadFile = File(...),
    is_search_by_missing: bool | None = None
) -> list[PetSearch]:
    allowed_types = {"image/jpeg", "image/png"}

    if file.content_type not in allowed_types:
        raise BadRequestException(
            "Please upload a valid image file — only JPG and PNG formats are supported."
        )

    ml_url = "http://ml:9000/search_pet"

    timeout = httpx.Timeout(
        connect=60.0,
        write=120.0,
        read=300.0,
        pool=None,
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            files = {"file": (file.filename, await file.read(), file.content_type)}
            response = await client.post(ml_url, files=files)
            response.raise_for_status()
            ml_response = response.json()
        except httpx.ReadTimeout:
            raise CustomException(503, "The ML service took too long to respond. Please try again.")
        except httpx.ConnectError:
            raise CustomException(503, "Unable to connect to the ML service. Please try again later.")
        except httpx.HTTPStatusError:
            raise CustomException(502, "The ML service returned an unexpected response.")
        except Exception:
            raise CustomException(500, "Something went wrong while processing the image.")

    if "embedding" not in ml_response:
        raise BadRequestException(ml_response.get("message", "Failed to detect a valid pet in the image."))

    embedding = ml_response["embedding"]

    if not embedding or not isinstance(embedding, list):
        raise BadRequestException(ml_response["message"])

    query_conditions = [
        FieldCondition(
            key="type",
            match=MatchValue(value="cat")
        )
    ]

    if is_search_by_missing is not None:
        query_conditions.append(
            FieldCondition(
                key="is_missing",
                match=MatchValue(value=is_search_by_missing)
            )
        )

    try:
        search_results = await asyncio.to_thread(
            search_pet,
            query_vector=embedding,
            collection_name="pet_profile_images",
            limit=5,
            query_filter=Filter(must=query_conditions),
        )
    except Exception as e:
        raise BadRequestException(f"Vector search failed: {e}")

    if not search_results:
        return []

    pet_scores = {}
    for hit in search_results:
        pet_id = hit["payload"]["pet_id"]
        score = hit["score"]
        pet_scores[pet_id] = max(pet_scores.get(pet_id, 0), score)

    query = select(Pet).options(selectinload(Pet.profile_images)).where(
        Pet.id.in_(pet_scores.keys()),
        ~Pet.is_deleted,
    )

    pets = (await db.execute(query)).scalars().all()

    data = sorted(
        (
            PetSearch.model_validate(
                {**PetRead.model_validate(pet).model_dump(), "score": pet_scores.get(pet.id, 0)}
            )
            for pet in pets
        ),
        key=lambda pet: pet.score,
        reverse=True,
    )

    return data


@router.get("/pets", response_model=PaginatedListResponse[PetRead])
async def read_all_pets(
    request: Request,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    page: int = 1,
    items_per_page: int = 10,
) -> dict[str, Any]:
    pets_with_profile_images = (
        await db.execute(
            select(Pet)
            .options(selectinload(Pet.profile_images))
            .where(~Pet.is_deleted)
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(Pet)
            .where(~Pet.is_deleted)
        )
    ).scalar_one()

    pets_data = {
        "data": [PetRead.from_orm(pet) for pet in pets_with_profile_images],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(crud_data=pets_data, page=page, items_per_page=items_per_page)
    return response


@router.get("/{username}/pets", response_model=PaginatedListResponse[PetRead])
@cache(
    key_prefix="{username}_pets:page_{page}:items_per_page:{items_per_page}",
    resource_id_name="username",
    expiration=60,
)
async def read_pets(
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

    pets_with_profile_images = (
        await db.execute(
            select(Pet)
            .options(selectinload(Pet.profile_images))
            .where(
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(Pet)
            .where(
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one()

    pets_data = {
        "data": [PetRead.from_orm(pet) for pet in pets_with_profile_images],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(crud_data=pets_data, page=page, items_per_page=items_per_page)
    return response


@router.get("/{username}/pet/{id}", response_model=PetRead)
@cache(key_prefix="{username}_pet_cache", resource_id_name="id")
async def read_pet(
    request: Request, username: str, id: int, db: Annotated[AsyncSession, Depends(async_get_db)]
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

    db_pet = (
        await db.execute(
            select(Pet)
            .options(selectinload(Pet.profile_images))
            .where(
                Pet.id == id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if db_pet is None:
        raise NotFoundException("Pet not found")

    return PetRead.model_validate(db_pet)


@router.patch("/{username}/pet/{id}")
@cache("{username}_pet_cache", resource_id_name="id", pattern_to_invalidate_extra=["{username}_pets:*"])
async def patch_pet(
    request: Request,
    username: str,
    id: int,
    values: PetUpdateWithProfileImages,
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

    db_pet = (
        await db.execute(
            select(Pet)
            .options(selectinload(Pet.profile_images))
            .where(
                Pet.id == id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet:
        raise NotFoundException("Pet not found")

    for field, value in values.model_dump(exclude_unset=True, exclude={"profile_images"}).items():
        setattr(db_pet, field, value)

    object_keys = [
        profile_image.image_object_key
        for profile_image in values.profile_images
        if not getattr(profile_image, "id", None) and getattr(profile_image, "image_object_key", None) is not None
    ]
    exists_map = await asyncio.to_thread(is_objects_exist, object_keys)
    missing_object_keys = [object_key for object_key, exists in exists_map.items() if not exists]
    if missing_object_keys:
        raise BadRequestException("Some image files might not have been uploaded. Please upload them and try again.")

    existing_profile_images = {profile_image.id: profile_image for profile_image in db_pet.profile_images}
    updated_profile_image_ids = {
        profile_image.id
        for profile_image in values.profile_images
        if getattr(profile_image, "id", None) is not None
    }

    invalid_ids = updated_profile_image_ids - set(existing_profile_images.keys())
    if invalid_ids:
        raise NotFoundException("Some profile images do not exist.")

    deleted_profile_image_ids = list(set(existing_profile_images) - updated_profile_image_ids)
    deleted_image_uuids = [str(existing_profile_images[image_id].uuid) for image_id in deleted_profile_image_ids]

    now = datetime.now(UTC)
    for profile_image_id in deleted_profile_image_ids:
        profile_image = existing_profile_images[profile_image_id]
        profile_image.is_deleted = True
        profile_image.deleted_at = now

    new_profile_image_models = []
    new_profile_images_payload = []

    for profile_image in values.profile_images:
        if getattr(profile_image, "id", None):
            existing_image = existing_profile_images[profile_image.id]
            existing_image.sort_order = profile_image.sort_order
            existing_image.is_primary = profile_image.is_primary
        elif getattr(profile_image, "image_object_key", None):
            new_profile_image = PetProfileImage(
                pet_id=db_pet.id,
                image_object_key=profile_image.image_object_key,
                sort_order=profile_image.sort_order,
                is_primary=profile_image.is_primary
            )
            db.add(new_profile_image)
            db_pet.profile_images.append(new_profile_image)
            new_profile_image_models.append(new_profile_image)

    await db.flush()

    primary_images = [
        profile_image for profile_image in db_pet.profile_images
        if not profile_image.is_deleted and profile_image.is_primary
    ]
    if len(primary_images) == 0:
        raise BadRequestException("A pet must have one primary profile image")
    if len(primary_images) > 1:
        raise BadRequestException("A pet can only have one primary profile image")

    if new_profile_image_models:
        new_profile_images_payload = [
            {
                "id": str(profile_image.uuid),
                "image_object_key": profile_image.image_object_key,
                "payload": {
                    "pet_id": db_pet.id,
                    "type": db_pet.type,
                    "is_missing": False
                }
            }
            for profile_image in new_profile_image_models
        ]

    try:
        await db.commit()

        if deleted_image_uuids:
            try:
                await asyncio.to_thread(delete_embedding, "pet_profile_images", deleted_image_uuids)
            except Exception as error:
                LOGGER.warning(
                    f"Failed to delete embeddings for pet_profile_images {deleted_image_uuids}: {error}"
            )

        if new_profile_images_payload:
            try:
                await queue.pool.enqueue_job("extract_features_task", new_profile_images_payload)
            except Exception as error:
                LOGGER.warning(f"Failed to enqueue feature extraction job: {error}")

    except SQLAlchemyError as error:
        await db.rollback()

        if isinstance(error, IntegrityError) and "uq_pet_primary_image" in str(error.orig):
            raise BadRequestException("A pet can have only one primary profile image")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the pet. Please try again later."
        )

    return {"message": "Pet updated"}


@router.delete("/{username}/pet/{id}")
@cache("{username}_pet_cache", resource_id_name="id", to_invalidate_extra={"{username}_pets": "{username}"})
async def erase_pet(
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

    db_pet = (
        await db.execute(
            select(Pet)
            .options(selectinload(Pet.profile_images))
            .where(
                Pet.id == id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet:
        raise NotFoundException("Pet not found")

    profile_image_uuids = [str(profile_image.uuid) for profile_image in db_pet.profile_images]

    now = datetime.now(UTC)
    db_pet.is_deleted = True
    db_pet.deleted_at = now
    db.add(db_pet)

    try:
        await db.execute(
            update(PetProfileImage)
            .where(
                PetProfileImage.pet_id == db_pet.id,
                ~PetProfileImage.is_deleted
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
            detail="An unexpected error occurred while deleting the pet. Please try again later."
        )

    if profile_image_uuids:
        try:
            await asyncio.to_thread(delete_embedding, "pet_profile_images", profile_image_uuids)
        except Exception as error:
            LOGGER.warning(f"Failed to delete embeddings for pet_profile_images {profile_image_uuids}: {error}")

    return {"message": "Pet deleted"}


@router.delete("/{username}/db_pet/{id}", dependencies=[Depends(get_authenticated_superuser)])
@cache("{username}_pet_cache", resource_id_name="id", to_invalidate_extra={"{username}_pets": "{username}"})
async def erase_db_pet(
    request: Request, username: str, id: int, db: Annotated[AsyncSession, Depends(async_get_db)]
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

    db_pet = (
        await db.execute(
            select(Pet)
            .options(selectinload(Pet.profile_images))
            .where(
                Pet.id == id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet:
        raise NotFoundException("Pet not found")

    profile_image_uuids = [str(profile_image.uuid) for profile_image in db_pet.profile_images]

    try:
        await db.delete(db_pet)
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the pet. Please try again later."
        )

    if profile_image_uuids:
        try:
            await asyncio.to_thread(delete_embedding, "pet_profile_images", profile_image_uuids)
        except Exception as error:
            LOGGER.warning(f"Failed to delete embeddings for pet_profile_images {profile_image_uuids}: {error}")

    return {"message": "Pet deleted from the database"}
