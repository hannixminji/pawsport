from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import rate_limiter_dependency
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.pet_medical_condition import (
    PetMedicalConditionCreate,
    PetMedicalConditionRead,
    PetMedicalConditionUpdate,
)
from app.services.pet_medical_condition_service import PetMedicalConditionService

router = APIRouter(prefix="/medical-conditions", tags=["Pet Medical Conditions"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> PetMedicalConditionService:
    return PetMedicalConditionService(db=db)


PetMedicalConditionServiceDependency = Annotated[PetMedicalConditionService, Depends(get_service)]
ActorDependency = Annotated[Actor, Depends(rate_limiter_dependency)]


@router.post("/search", response_model=PaginatedResponse[PetMedicalConditionRead], status_code=status.HTTP_200_OK)
async def search_pet_medical_conditions(
    search_request: SearchRequest,
    actor: ActorDependency,
    service: PetMedicalConditionServiceDependency,
    user_id: Annotated[int | None, Query(alias="userId")] = None,
    pet_id: Annotated[int | None, Query(alias="petId")] = None,
) -> PaginatedResponse[PetMedicalConditionRead]:
    return await service.search(actor=actor, search_request=search_request, user_id=user_id, pet_id=pet_id)


@router.post("/{pet_id}", response_model=PetMedicalConditionRead, status_code=status.HTTP_201_CREATED)
async def create_pet_medical_condition(
    request: Request,
    pet_id: int,
    payload: PetMedicalConditionCreate,
    actor: ActorDependency,
    service: PetMedicalConditionServiceDependency,
) -> PetMedicalConditionRead:
    result = await service.create(actor=actor, pet_id=pet_id, medical_condition_input=payload)
    await invalidate_namespace("app:pet-medical-conditions")
    return result


@router.get("", response_model=PaginatedResponse[PetMedicalConditionRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:pet-medical-conditions:list",
    resource_id_name=["page", "items_per_page", "user_id", "pet_id"],
    namespace="app:pet-medical-conditions",
    expiration=60,
)
async def list_pet_medical_conditions(
    request: Request,
    actor: ActorDependency,
    service: PetMedicalConditionServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
    user_id: Annotated[int | None, Query(alias="userId")] = None,
    pet_id: Annotated[int | None, Query(alias="petId")] = None,
) -> PaginatedResponse[PetMedicalConditionRead]:
    return await service.get_pet_medical_conditions(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
        user_id=user_id,
        pet_id=pet_id,
    )


@router.get("/{medical_condition_id}", response_model=PetMedicalConditionRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:pet-medical-conditions:detail",
    resource_id_name="medical_condition_id",
    expiration=60,
)
async def get_pet_medical_condition(
    request: Request,
    medical_condition_id: int,
    actor: ActorDependency,
    service: PetMedicalConditionServiceDependency,
) -> PetMedicalConditionRead:
    return await service.get_pet_medical_condition(actor=actor, medical_condition_id=medical_condition_id)


@router.patch("/{medical_condition_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="app:pet-medical-conditions:detail",
    resource_id_name="medical_condition_id",
    namespaces_to_invalidate=["app:pet-medical-conditions"],
)
async def soft_delete_pet_medical_condition(
    request: Request,
    medical_condition_id: int,
    actor: ActorDependency,
    service: PetMedicalConditionServiceDependency,
) -> None:
    await service.soft_delete(actor=actor, medical_condition_id=medical_condition_id)


@router.patch("/{medical_condition_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="app:pet-medical-conditions:detail",
    resource_id_name="medical_condition_id",
    namespaces_to_invalidate=["app:pet-medical-conditions"],
)
async def update_pet_medical_condition(
    request: Request,
    medical_condition_id: int,
    payload: PetMedicalConditionUpdate,
    actor: ActorDependency,
    service: PetMedicalConditionServiceDependency,
) -> None:
    await service.update(actor=actor, medical_condition_id=medical_condition_id, medical_condition_input=payload)
