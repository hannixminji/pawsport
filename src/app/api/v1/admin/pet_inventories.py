from typing import Annotated

from fastapi import Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter, csrf_exempt
from app.api.dependencies import get_current_superuser_actor, require_permission
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.pet_inventory import (
    PetInventoryBulkDelete,
    PetInventoryCreateWithImages,
    PetInventoryRead,
    PetInventoryUpdateWithImages,
)
from app.services.pet_inventory_service import PetInventoryService

router = CSRFProtectedRouter(prefix="/inventory", tags=["Pet Inventory"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> PetInventoryService:
    return PetInventoryService(db=db)


PetInventoryServiceDependency = Annotated[PetInventoryService, Depends(get_service)]
SuperuserActorDependency = Annotated[Actor, Depends(get_current_superuser_actor)]


@csrf_exempt
@router.post("/search", response_model=PaginatedResponse[PetInventoryRead], status_code=status.HTTP_200_OK)
async def search_inventory_items(
    search_request: SearchRequest,
    actor: Annotated[Actor, Depends(require_permission("pet_inventory:search"))],
    service: PetInventoryServiceDependency,
    user_id: Annotated[int | None, Query(alias="userId")] = None,
) -> PaginatedResponse[PetInventoryRead]:
    return await service.search(actor=actor, search_request=search_request, user_id=user_id)


@router.post("/{user_id}", response_model=PetInventoryRead, status_code=status.HTTP_201_CREATED)
async def create_inventory_item(
    request: Request,
    user_id: int,
    payload: PetInventoryCreateWithImages,
    actor: Annotated[Actor, Depends(require_permission("pet_inventory:create"))],
    service: PetInventoryServiceDependency,
) -> PetInventoryRead:
    result = await service.create(actor=actor, user_id=user_id, inventory_input=payload)
    await invalidate_namespace("pet-inventory")
    return result


@router.get("", response_model=PaginatedResponse[PetInventoryRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:pet-inventory:list",
    resource_id_name=["page", "items_per_page", "user_id"],
    namespace="pet-inventory",
    expiration=60,
)
async def list_inventory_items(
    request: Request,
    actor: Annotated[Actor, Depends(require_permission("pet_inventory:read"))],
    service: PetInventoryServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
    user_id: Annotated[int | None, Query(alias="userId")] = None,
) -> PaginatedResponse[PetInventoryRead]:
    return await service.get_inventory_items(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
        user_id=user_id,
    )


@router.get("/{inventory_id}", response_model=PetInventoryRead, status_code=status.HTTP_200_OK)
@cache(key_prefix="admin:pet-inventory:detail", resource_id_name="inventory_id", expiration=60)
async def get_inventory_item(
    request: Request,
    inventory_id: int,
    actor: Annotated[Actor, Depends(require_permission("pet_inventory:read"))],
    service: PetInventoryServiceDependency,
) -> PetInventoryRead:
    return await service.get_inventory(actor=actor, inventory_id=inventory_id)


@router.patch("/bulk/delete", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_soft_delete_inventory_items(
    payload: PetInventoryBulkDelete,
    actor: Annotated[Actor, Depends(require_permission("pet_inventory:bulk_soft_delete"))],
    service: PetInventoryServiceDependency,
) -> None:
    await service.bulk_soft_delete(actor=actor, inventory_ids=payload.ids)
    await invalidate_namespace("pet-inventory")


@router.patch("/{inventory_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:pet-inventory:detail",
    resource_id_name="inventory_id",
    namespaces_to_invalidate=["pet-inventory"],
)
async def soft_delete_inventory_item(
    request: Request,
    inventory_id: int,
    actor: Annotated[Actor, Depends(require_permission("pet_inventory:soft_delete"))],
    service: PetInventoryServiceDependency,
) -> None:
    await service.soft_delete(actor=actor, inventory_id=inventory_id)


@router.patch("/{inventory_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:pet-inventory:detail",
    resource_id_name="inventory_id",
    namespaces_to_invalidate=["pet-inventory"],
)
async def update_inventory_item(
    request: Request,
    inventory_id: int,
    payload: PetInventoryUpdateWithImages,
    actor: Annotated[Actor, Depends(require_permission("pet_inventory:update"))],
    service: PetInventoryServiceDependency,
) -> None:
    await service.update(actor=actor, inventory_id=inventory_id, inventory_input=payload)


@router.delete("/bulk", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_hard_delete_inventory_items(
    payload: PetInventoryBulkDelete,
    actor: SuperuserActorDependency,
    service: PetInventoryServiceDependency,
) -> None:
    await service.bulk_hard_delete(actor=actor, inventory_ids=payload.ids)
    await invalidate_namespace("pet-inventory")


@router.delete("/{inventory_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:pet-inventory:detail",
    resource_id_name="inventory_id",
    namespaces_to_invalidate=["pet-inventory"],
)
async def hard_delete_inventory_item(
    request: Request,
    inventory_id: int,
    actor: SuperuserActorDependency,
    service: PetInventoryServiceDependency,
) -> None:
    await service.hard_delete(actor=actor, inventory_id=inventory_id)
