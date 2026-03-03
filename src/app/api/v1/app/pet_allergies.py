from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import rate_limiter_dependency
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.pet_allergy import PetAllergyCreate, PetAllergyRead, PetAllergyUpdate
from app.services.pet_allergy_service import PetAllergyService

router = APIRouter(prefix="/allergies", tags=["Pet Allergies"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> PetAllergyService:
    return PetAllergyService(db=db)


PetAllergyServiceDependency = Annotated[PetAllergyService, Depends(get_service)]
ActorDependency = Annotated[Actor, Depends(rate_limiter_dependency)]


@router.post("/search", response_model=PaginatedResponse[PetAllergyRead], status_code=status.HTTP_200_OK)
async def search_pet_allergies(
    search_request: SearchRequest,
    actor: ActorDependency,
    service: PetAllergyServiceDependency,
    user_id: Annotated[int | None, Query(alias="userId")] = None,
    pet_id: Annotated[int | None, Query(alias="petId")] = None,
) -> PaginatedResponse[PetAllergyRead]:
    return await service.search(actor=actor, search_request=search_request, user_id=user_id, pet_id=pet_id)


@router.post("/{pet_id}", response_model=PetAllergyRead, status_code=status.HTTP_201_CREATED)
async def create_pet_allergy(
    request: Request,
    pet_id: int,
    payload: PetAllergyCreate,
    actor: ActorDependency,
    service: PetAllergyServiceDependency,
) -> PetAllergyRead:
    result = await service.create(actor=actor, pet_id=pet_id, allergy_input=payload)
    await invalidate_namespace("app:pet-allergies")
    return result


@router.get("", response_model=PaginatedResponse[PetAllergyRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:pet-allergies:list",
    resource_id_name=["page", "items_per_page", "user_id", "pet_id"],
    namespace="app:pet-allergies",
    expiration=60,
)
async def list_pet_allergies(
    request: Request,
    actor: ActorDependency,
    service: PetAllergyServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
    user_id: Annotated[int | None, Query(alias="userId")] = None,
    pet_id: Annotated[int | None, Query(alias="petId")] = None,
) -> PaginatedResponse[PetAllergyRead]:
    return await service.get_pet_allergies(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
        user_id=user_id,
        pet_id=pet_id,
    )


@router.get("/{allergy_id}", response_model=PetAllergyRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:pet-allergies:detail",
    resource_id_name="allergy_id",
    expiration=60,
)
async def get_pet_allergy(
    request: Request,
    allergy_id: int,
    actor: ActorDependency,
    service: PetAllergyServiceDependency,
) -> PetAllergyRead:
    return await service.get_pet_allergy(actor=actor, allergy_id=allergy_id)


@router.patch("/{allergy_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="app:pet-allergies:detail",
    resource_id_name="allergy_id",
    namespaces_to_invalidate=["app:pet-allergies"],
)
async def soft_delete_pet_allergy(
    request: Request,
    allergy_id: int,
    actor: ActorDependency,
    service: PetAllergyServiceDependency,
) -> None:
    await service.soft_delete(actor=actor, allergy_id=allergy_id)


@router.patch("/{allergy_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="app:pet-allergies:detail",
    resource_id_name="allergy_id",
    namespaces_to_invalidate=["app:pet-allergies"],
)
async def update_pet_allergy(
    request: Request,
    allergy_id: int,
    payload: PetAllergyUpdate,
    actor: ActorDependency,
    service: PetAllergyServiceDependency,
) -> None:
    await service.update(actor=actor, allergy_id=allergy_id, allergy_input=payload)
