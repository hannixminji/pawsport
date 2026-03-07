from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import rate_limiter_dependency
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.pet_inventory import PetInventoryCreateWithImages, PetInventoryRead, PetInventoryUpdateWithImages
from app.services.pet_inventory_service import PetInventoryService

router = APIRouter(prefix="/inventory", tags=["Pet Inventory"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> PetInventoryService:
    return PetInventoryService(db=db)


PetInventoryServiceDependency = Annotated[PetInventoryService, Depends(get_service)]
ActorDependency = Annotated[Actor, Depends(rate_limiter_dependency)]


@router.post("/search", response_model=PaginatedResponse[PetInventoryRead], status_code=status.HTTP_200_OK)
async def search_inventory_items(
    search_request: SearchRequest,
    actor: ActorDependency,
    service: PetInventoryServiceDependency,
) -> PaginatedResponse[PetInventoryRead]:
    return await service.search(actor=actor, search_request=search_request, user_id=actor.id)


@router.post("", response_model=PetInventoryRead, status_code=status.HTTP_201_CREATED)
async def create_inventory_item(
    request: Request,
    payload: PetInventoryCreateWithImages,
    actor: ActorDependency,
    service: PetInventoryServiceDependency,
) -> PetInventoryRead:
    result = await service.create(actor=actor, user_id=actor.id, inventory_input=payload)
    await invalidate_namespace("pet-inventory")
    return result


@router.get("", response_model=PaginatedResponse[PetInventoryRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:pet-inventory:list",
    resource_id_name=["page", "items_per_page", "actor.id"],
    namespace="pet-inventory",
    expiration=60,
)
async def list_inventory_items(
    request: Request,
    actor: ActorDependency,
    service: PetInventoryServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
) -> PaginatedResponse[PetInventoryRead]:
    return await service.get_inventory_items(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
        user_id=actor.id,
    )


@router.get("/{inventory_id}", response_model=PetInventoryRead, status_code=status.HTTP_200_OK)
@cache(key_prefix="app:pet-inventory:detail", resource_id_name="inventory_id", expiration=60)
async def get_inventory_item(
    request: Request,
    inventory_id: int,
    actor: ActorDependency,
    service: PetInventoryServiceDependency,
) -> PetInventoryRead:
    return await service.get_inventory(actor=actor, inventory_id=inventory_id)


@router.patch("/{inventory_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="app:pet-inventory:detail",
    resource_id_name="inventory_id",
    namespaces_to_invalidate=["pet-inventory"],
)
async def soft_delete_inventory_item(
    request: Request,
    inventory_id: int,
    actor: ActorDependency,
    service: PetInventoryServiceDependency,
) -> None:
    await service.soft_delete(actor=actor, inventory_id=inventory_id)


@router.patch("/{inventory_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="app:pet-inventory:detail",
    resource_id_name="inventory_id",
    namespaces_to_invalidate=["pet-inventory"],
)
async def update_inventory_item(
    request: Request,
    inventory_id: int,
    payload: PetInventoryUpdateWithImages,
    actor: ActorDependency,
    service: PetInventoryServiceDependency,
) -> None:
    await service.update(actor=actor, inventory_id=inventory_id, inventory_input=payload)
