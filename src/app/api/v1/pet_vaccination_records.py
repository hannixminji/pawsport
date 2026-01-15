import asyncio
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.dependencies import get_authenticated_user
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import BadRequestException, ForbiddenException, NotFoundException
from ...core.utils.cache import cache
from ...core.utils.google_cloud_storage import is_objects_exist
from ...models.pet import Pet
from ...models.user import User
from ...models.vaccination_record import VaccinationRecord
from ...schemas.user import UserRead
from ...schemas.vaccination_record import PetVaccinationRecordCreate, PetVaccinationRecordRead

router = APIRouter(tags=["pet_vaccination_records"])


@router.post(
    "/{username}/pet/{pet_id}/vaccination_records",
    response_model=list[PetVaccinationRecordRead],
    status_code=201,
)
async def write_vaccination_records(
    username: str,
    pet_id: int,
    vaccination_records: list[PetVaccinationRecordCreate],
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> list[PetVaccinationRecordRead]:
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

    object_keys = [vaccination_record.file_object_key for vaccination_record in vaccination_records]
    exists_map = await asyncio.to_thread(is_objects_exist, object_keys)
    missing_object_keys = [object_key for object_key, exists in exists_map.items() if not exists]
    if missing_object_keys:
        raise BadRequestException("Some image files might not have been uploaded. Please upload them and try again.")

    vaccination_record_models = []
    for vaccination_record in vaccination_records:
        vaccination_record_model = VaccinationRecord(
            pet_id=db_pet_id,
            file_object_key=vaccination_record.file_object_key,
            expiry_date=vaccination_record.expiry_date
        )
        db.add(vaccination_record_model)
        vaccination_record_models.append(vaccination_record_model)

    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add the vaccination records due to a server error. Please try again later."
        )

    for vaccination_record_model in vaccination_record_models:
        await db.refresh(vaccination_record_model)

    return [
        PetVaccinationRecordRead.model_validate(vaccination_record_model)
        for vaccination_record_model in vaccination_record_models
    ]


@router.get(
    "/{username}/pet/{pet_id}/vaccination_records",
    response_model=list[PetVaccinationRecordRead]
)
@cache(
    key_prefix="{username}_vaccination_records:pet_{pet_id}",
    resource_id_name="pet_id",
    expiration=60
)
async def read_vaccination_records(
    username: str,
    pet_id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
) -> list[PetVaccinationRecordRead]:
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

    db_vaccination_records = (
        await db.execute(
            select(VaccinationRecord)
            .where(
                VaccinationRecord.pet_id == pet_id,
                ~VaccinationRecord.is_deleted
            )
        )
    ).scalars().all()

    return [
        PetVaccinationRecordRead.model_validate(vaccination_record)
        for vaccination_record in db_vaccination_records
    ]


@router.get(
    "/{username}/pet/{pet_id}/vaccination_records/{id}",
    response_model=PetVaccinationRecordRead
)
@cache(
    key_prefix="{username}_vaccination_record_cache",
    resource_id_name="id"
)
async def read_vaccination_record(
    username: str,
    pet_id: int,
    id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
) -> PetVaccinationRecordRead:
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

    db_vaccination_record = (
        await db.execute(
            select(VaccinationRecord)
            .where(
                VaccinationRecord.id == id,
                VaccinationRecord.pet_id == pet_id,
                ~VaccinationRecord.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_vaccination_record:
        raise NotFoundException("Vaccination record not found")

    return PetVaccinationRecordRead.model_validate(db_vaccination_record)


@router.delete("/{username}/pet/{pet_id}/vaccination_records/{id}")
@cache(
    "{username}_vaccination_record_cache",
    resource_id_name="id",
    to_invalidate_extra={"{username}_vaccination_records:pet_{pet_id}": "{pet_id}"}
)
async def erase_vaccination_record(
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

    db_vaccination_record = (
        await db.execute(
            select(VaccinationRecord)
            .where(
                VaccinationRecord.id == id,
                VaccinationRecord.pet_id == pet_id,
                ~VaccinationRecord.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_vaccination_record:
        raise NotFoundException("Vaccination record not found")

    now = datetime.now(UTC)
    db_vaccination_record.is_deleted = True
    db_vaccination_record.deleted_at = now
    db.add(db_vaccination_record)

    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete vaccination record. Please try again later."
        )

    return {"message": "Vaccination record deleted"}
