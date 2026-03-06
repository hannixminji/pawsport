from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import rate_limiter_dependency
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.pet_vaccination_record import (
    PetVaccinationRecordCreateWithAttachments,
    PetVaccinationRecordRead,
    PetVaccinationRecordUpdateWithAttachments,
)
from app.services.pet_vaccination_record_service import PetVaccinationRecordService

router = APIRouter(prefix="/vaccination-records", tags=["Pet Vaccination Records"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> PetVaccinationRecordService:
    return PetVaccinationRecordService(db=db)


PetVaccinationRecordServiceDependency = Annotated[PetVaccinationRecordService, Depends(get_service)]
ActorDependency = Annotated[Actor, Depends(rate_limiter_dependency)]


@router.post("/search", response_model=PaginatedResponse[PetVaccinationRecordRead], status_code=status.HTTP_200_OK)
async def search_vaccination_records(
    search_request: SearchRequest,
    actor: ActorDependency,
    service: PetVaccinationRecordServiceDependency,
    pet_id: Annotated[int | None, Query(alias="petId")] = None,
) -> PaginatedResponse[PetVaccinationRecordRead]:
    return await service.search(actor=actor, search_request=search_request, user_id=actor.id, pet_id=pet_id)


@router.post("/{pet_id}", response_model=PetVaccinationRecordRead, status_code=status.HTTP_201_CREATED)
async def create_vaccination_record(
    request: Request,
    pet_id: int,
    payload: PetVaccinationRecordCreateWithAttachments,
    actor: ActorDependency,
    service: PetVaccinationRecordServiceDependency,
) -> PetVaccinationRecordRead:
    result = await service.create(actor=actor, pet_id=pet_id, vaccination_record_input=payload)
    await invalidate_namespace("app:pet-vaccination-records")
    return result


@router.get("", response_model=PaginatedResponse[PetVaccinationRecordRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:pet-vaccination-records:list",
    resource_id_name=["page", "items_per_page", "pet_id"],
    namespace="app:pet-vaccination-records",
    expiration=60,
)
async def list_vaccination_records(
    request: Request,
    actor: ActorDependency,
    service: PetVaccinationRecordServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
    pet_id: Annotated[int | None, Query(alias="petId")] = None,
) -> PaginatedResponse[PetVaccinationRecordRead]:
    return await service.get_vaccination_records(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
        user_id=actor.id,
        pet_id=pet_id,
    )


@router.get("/{vaccination_record_id}", response_model=PetVaccinationRecordRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:pet-vaccination-records:detail",
    resource_id_name="vaccination_record_id",
    expiration=60,
)
async def get_vaccination_record(
    request: Request,
    vaccination_record_id: int,
    actor: ActorDependency,
    service: PetVaccinationRecordServiceDependency,
) -> PetVaccinationRecordRead:
    return await service.get_vaccination_record(actor=actor, vaccination_record_id=vaccination_record_id)


@router.patch("/{vaccination_record_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="app:pet-vaccination-records:detail",
    resource_id_name="vaccination_record_id",
    namespaces_to_invalidate=["app:pet-vaccination-records"],
)
async def soft_delete_vaccination_record(
    request: Request,
    vaccination_record_id: int,
    actor: ActorDependency,
    service: PetVaccinationRecordServiceDependency,
) -> None:
    await service.soft_delete(actor=actor, vaccination_record_id=vaccination_record_id)


@router.patch("/{vaccination_record_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="app:pet-vaccination-records:detail",
    resource_id_name="vaccination_record_id",
    namespaces_to_invalidate=["app:pet-vaccination-records"],
)
async def update_vaccination_record(
    request: Request,
    vaccination_record_id: int,
    payload: PetVaccinationRecordUpdateWithAttachments,
    actor: ActorDependency,
    service: PetVaccinationRecordServiceDependency,
) -> None:
    await service.update(actor=actor, vaccination_record_id=vaccination_record_id, vaccination_record_input=payload)
