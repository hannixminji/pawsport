from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import rate_limiter_dependency
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.pet_medication import PetMedicationCreate, PetMedicationRead, PetMedicationUpdate
from app.services.pet_medication_service import PetMedicationService

router = APIRouter(prefix="/medications", tags=["Pet Medications"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> PetMedicationService:
    return PetMedicationService(db=db)


PetMedicationServiceDependency = Annotated[PetMedicationService, Depends(get_service)]
ActorDependency = Annotated[Actor, Depends(rate_limiter_dependency)]


@router.post("/search", response_model=PaginatedResponse[PetMedicationRead], status_code=status.HTTP_200_OK)
async def search_pet_medications(
    search_request: SearchRequest,
    actor: ActorDependency,
    service: PetMedicationServiceDependency,
    pet_id: Annotated[int | None, Query(alias="petId")] = None,
) -> PaginatedResponse[PetMedicationRead]:
    return await service.search(actor=actor, search_request=search_request, user_id=actor.id, pet_id=pet_id)


@router.post("/{pet_id}", response_model=PetMedicationRead, status_code=status.HTTP_201_CREATED)
async def create_pet_medication(
    request: Request,
    pet_id: int,
    payload: PetMedicationCreate,
    actor: ActorDependency,
    service: PetMedicationServiceDependency,
) -> PetMedicationRead:
    result = await service.create(actor=actor, pet_id=pet_id, medication_input=payload)
    await invalidate_namespace("pet-medications")
    return result


@router.get("", response_model=PaginatedResponse[PetMedicationRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:pet-medications:list",
    resource_id_name=["page", "items_per_page", "pet_id"],
    namespace="pet-medications",
    expiration=60,
)
async def list_pet_medications(
    request: Request,
    actor: ActorDependency,
    service: PetMedicationServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
    pet_id: Annotated[int | None, Query(alias="petId")] = None,
) -> PaginatedResponse[PetMedicationRead]:
    return await service.get_pet_medications(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
        user_id=actor.id,
        pet_id=pet_id,
    )


@router.get("/{medication_id}", response_model=PetMedicationRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:pet-medications:detail",
    resource_id_name="medication_id",
    expiration=60,
)
async def get_pet_medication(
    request: Request,
    medication_id: int,
    actor: ActorDependency,
    service: PetMedicationServiceDependency,
) -> PetMedicationRead:
    return await service.get_pet_medication(actor=actor, medication_id=medication_id)


@router.patch("/{medication_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="app:pet-medications:detail",
    resource_id_name="medication_id",
    namespaces_to_invalidate=["pet-medications"],
)
async def soft_delete_pet_medication(
    request: Request,
    medication_id: int,
    actor: ActorDependency,
    service: PetMedicationServiceDependency,
) -> None:
    await service.soft_delete(actor=actor, medication_id=medication_id)


@router.patch("/{medication_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="app:pet-medications:detail",
    resource_id_name="medication_id",
    namespaces_to_invalidate=["pet-medications"],
)
async def update_pet_medication(
    request: Request,
    medication_id: int,
    payload: PetMedicationUpdate,
    actor: ActorDependency,
    service: PetMedicationServiceDependency,
) -> None:
    await service.update(actor=actor, medication_id=medication_id, medication_input=payload)
