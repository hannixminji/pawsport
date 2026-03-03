from typing import Annotated

from fastapi import Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter
from app.api.dependencies import get_current_admin_actor, get_current_superuser_actor
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.pet_vaccination_record import (
    PetVaccinationRecordBulkDelete,
    PetVaccinationRecordCreate,
    PetVaccinationRecordRead,
    PetVaccinationRecordUpdate,
)
from app.services.pet_vaccination_record_service import PetVaccinationRecordService

router = CSRFProtectedRouter(prefix="/vaccination-records", tags=["Pet Vaccination Records"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> PetVaccinationRecordService:
    return PetVaccinationRecordService(db=db)


PetVaccinationRecordServiceDependency = Annotated[PetVaccinationRecordService, Depends(get_service)]
SuperuserActorDependency = Annotated[Actor, Depends(get_current_superuser_actor)]
AdminActorDependency = Annotated[Actor, Depends(get_current_admin_actor)]


@router.post("/search", response_model=PaginatedResponse[PetVaccinationRecordRead], status_code=status.HTTP_200_OK)
async def search_vaccination_records(
    search_request: SearchRequest,
    actor: AdminActorDependency,
    service: PetVaccinationRecordServiceDependency,
    user_id: Annotated[int | None, Query(alias="userId")] = None,
    pet_id: Annotated[int | None, Query(alias="petId")] = None,
) -> PaginatedResponse[PetVaccinationRecordRead]:
    return await service.search(actor=actor, search_request=search_request, user_id=user_id, pet_id=pet_id)


@router.post("/{pet_id}", response_model=PetVaccinationRecordRead, status_code=status.HTTP_201_CREATED)
async def create_vaccination_record(
    request: Request,
    pet_id: int,
    payload: PetVaccinationRecordCreate,
    actor: AdminActorDependency,
    service: PetVaccinationRecordServiceDependency,
) -> PetVaccinationRecordRead:
    result = await service.create(actor=actor, pet_id=pet_id, vaccination_record_input=payload)
    await invalidate_namespace("admin:pet-vaccination-records")
    return result


@router.get("", response_model=PaginatedResponse[PetVaccinationRecordRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:pet-vaccination-records:list",
    resource_id_name=["page", "items_per_page", "user_id", "pet_id"],
    namespace="admin:pet-vaccination-records",
    expiration=60,
)
async def list_vaccination_records(
    request: Request,
    actor: AdminActorDependency,
    service: PetVaccinationRecordServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
    user_id: Annotated[int | None, Query(alias="userId")] = None,
    pet_id: Annotated[int | None, Query(alias="petId")] = None,
) -> PaginatedResponse[PetVaccinationRecordRead]:
    return await service.get_vaccination_records(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
        user_id=user_id,
        pet_id=pet_id,
    )


@router.get("/{vaccination_record_id}", response_model=PetVaccinationRecordRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:pet-vaccination-records:detail",
    resource_id_name="vaccination_record_id",
    expiration=60,
)
async def get_vaccination_record(
    request: Request,
    vaccination_record_id: int,
    actor: AdminActorDependency,
    service: PetVaccinationRecordServiceDependency,
) -> PetVaccinationRecordRead:
    return await service.get_vaccination_record(actor=actor, vaccination_record_id=vaccination_record_id)


@router.patch("/bulk/delete", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_soft_delete_vaccination_records(
    payload: PetVaccinationRecordBulkDelete,
    actor: AdminActorDependency,
    service: PetVaccinationRecordServiceDependency,
) -> None:
    await service.bulk_soft_delete(actor=actor, vaccination_record_ids=payload.ids)
    await invalidate_namespace("admin:pet-vaccination-records")


@router.patch("/{vaccination_record_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:pet-vaccination-records:detail",
    resource_id_name="vaccination_record_id",
    namespaces_to_invalidate=["admin:pet-vaccination-records"],
)
async def soft_delete_vaccination_record(
    request: Request,
    vaccination_record_id: int,
    actor: AdminActorDependency,
    service: PetVaccinationRecordServiceDependency,
) -> None:
    await service.soft_delete(actor=actor, vaccination_record_id=vaccination_record_id)


@router.patch("/{vaccination_record_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:pet-vaccination-records:detail",
    resource_id_name="vaccination_record_id",
    namespaces_to_invalidate=["admin:pet-vaccination-records"],
)
async def update_vaccination_record(
    request: Request,
    vaccination_record_id: int,
    payload: PetVaccinationRecordUpdate,
    actor: AdminActorDependency,
    service: PetVaccinationRecordServiceDependency,
) -> None:
    await service.update(actor=actor, vaccination_record_id=vaccination_record_id, vaccination_record_input=payload)


@router.delete("/bulk", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_hard_delete_vaccination_records(
    payload: PetVaccinationRecordBulkDelete,
    actor: SuperuserActorDependency,
    service: PetVaccinationRecordServiceDependency,
) -> None:
    await service.bulk_hard_delete(actor=actor, vaccination_record_ids=payload.ids)
    await invalidate_namespace("admin:pet-vaccination-records")


@router.delete("/{vaccination_record_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:pet-vaccination-records:detail",
    resource_id_name="vaccination_record_id",
    namespaces_to_invalidate=["admin:pet-vaccination-records"],
)
async def hard_delete_vaccination_record(
    request: Request,
    vaccination_record_id: int,
    actor: SuperuserActorDependency,
    service: PetVaccinationRecordServiceDependency,
) -> None:
    await service.hard_delete(actor=actor, vaccination_record_id=vaccination_record_id)
