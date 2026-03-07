from typing import Annotated

from fastapi import Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter, csrf_exempt
from app.api.dependencies import get_current_superuser_actor, require_permission
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.pet_medical_condition import (
    PetMedicalConditionBulkDelete,
    PetMedicalConditionCreate,
    PetMedicalConditionRead,
    PetMedicalConditionUpdate,
)
from app.services.pet_medical_condition_service import PetMedicalConditionService

router = CSRFProtectedRouter(prefix="/medical-conditions", tags=["Pet Medical Conditions"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> PetMedicalConditionService:
    return PetMedicalConditionService(db=db)


PetMedicalConditionServiceDependency = Annotated[PetMedicalConditionService, Depends(get_service)]
SuperuserActorDependency = Annotated[Actor, Depends(get_current_superuser_actor)]


@csrf_exempt
@router.post("/search", response_model=PaginatedResponse[PetMedicalConditionRead], status_code=status.HTTP_200_OK)
async def search_pet_medical_conditions(
    search_request: SearchRequest,
    actor: Annotated[Actor, Depends(require_permission("pet_medical_condition:search"))],
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
    actor: Annotated[Actor, Depends(require_permission("pet_medical_condition:create"))],
    service: PetMedicalConditionServiceDependency,
) -> PetMedicalConditionRead:
    result = await service.create(actor=actor, pet_id=pet_id, medical_condition_input=payload)
    await invalidate_namespace("pet-medical-conditions")
    return result


@router.get("", response_model=PaginatedResponse[PetMedicalConditionRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:pet-medical-conditions:list",
    resource_id_name=["page", "items_per_page", "user_id", "pet_id"],
    namespace="pet-medical-conditions",
    expiration=60,
)
async def list_pet_medical_conditions(
    request: Request,
    actor: Annotated[Actor, Depends(require_permission("pet_medical_condition:read"))],
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
    key_prefix="admin:pet-medical-conditions:detail",
    resource_id_name="medical_condition_id",
    expiration=60,
)
async def get_pet_medical_condition(
    request: Request,
    medical_condition_id: int,
    actor: Annotated[Actor, Depends(require_permission("pet_medical_condition:read"))],
    service: PetMedicalConditionServiceDependency,
) -> PetMedicalConditionRead:
    return await service.get_pet_medical_condition(actor=actor, medical_condition_id=medical_condition_id)


@router.patch("/bulk/delete", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_soft_delete_pet_medical_conditions(
    payload: PetMedicalConditionBulkDelete,
    actor: Annotated[Actor, Depends(require_permission("pet_medical_condition:bulk_soft_delete"))],
    service: PetMedicalConditionServiceDependency,
) -> None:
    await service.bulk_soft_delete(actor=actor, medical_condition_ids=payload.ids)
    await invalidate_namespace("pet-medical-conditions")


@router.patch("/{medical_condition_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:pet-medical-conditions:detail",
    resource_id_name="medical_condition_id",
    namespaces_to_invalidate=["pet-medical-conditions"],
)
async def soft_delete_pet_medical_condition(
    request: Request,
    medical_condition_id: int,
    actor: Annotated[Actor, Depends(require_permission("pet_medical_condition:soft_delete"))],
    service: PetMedicalConditionServiceDependency,
) -> None:
    await service.soft_delete(actor=actor, medical_condition_id=medical_condition_id)


@router.patch("/{medical_condition_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:pet-medical-conditions:detail",
    resource_id_name="medical_condition_id",
    namespaces_to_invalidate=["pet-medical-conditions"],
)
async def update_pet_medical_condition(
    request: Request,
    medical_condition_id: int,
    payload: PetMedicalConditionUpdate,
    actor: Annotated[Actor, Depends(require_permission("pet_medical_condition:update"))],
    service: PetMedicalConditionServiceDependency,
) -> None:
    await service.update(actor=actor, medical_condition_id=medical_condition_id, medical_condition_input=payload)


@router.delete("/bulk", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_hard_delete_pet_medical_conditions(
    payload: PetMedicalConditionBulkDelete,
    actor: SuperuserActorDependency,
    service: PetMedicalConditionServiceDependency,
) -> None:
    await service.bulk_hard_delete(actor=actor, medical_condition_ids=payload.ids)
    await invalidate_namespace("pet-medical-conditions")


@router.delete("/{medical_condition_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:pet-medical-conditions:detail",
    resource_id_name="medical_condition_id",
    namespaces_to_invalidate=["pet-medical-conditions"],
)
async def hard_delete_pet_medical_condition(
    request: Request,
    medical_condition_id: int,
    actor: SuperuserActorDependency,
    service: PetMedicalConditionServiceDependency,
) -> None:
    await service.hard_delete(actor=actor, medical_condition_id=medical_condition_id)
