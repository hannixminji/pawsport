from typing import Annotated

from fastapi import Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter, csrf_exempt
from app.api.dependencies import get_current_superuser_actor, require_permission
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.tier import TierBulkDelete, TierCreate, TierRead, TierUpdate
from app.services.tier_service import TierService

router = CSRFProtectedRouter(prefix="/tiers", tags=["Tiers"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> TierService:
    return TierService(db=db)


TierServiceDependency = Annotated[TierService, Depends(get_service)]
SuperuserActorDependency = Annotated[Actor, Depends(get_current_superuser_actor)]


@csrf_exempt
@router.post("/search", response_model=PaginatedResponse[TierRead], status_code=status.HTTP_200_OK)
async def search_tiers(
    search_request: SearchRequest,
    actor: Annotated[Actor, Depends(require_permission("tier:search"))],
    service: TierServiceDependency,
) -> PaginatedResponse[TierRead]:
    return await service.search(actor=actor, search_request=search_request)


@router.post("", response_model=TierRead, status_code=status.HTTP_201_CREATED)
async def create_tier(
    request: Request,
    payload: TierCreate,
    actor: Annotated[Actor, Depends(require_permission("tier:create"))],
    service: TierServiceDependency,
) -> TierRead:
    result = await service.create(actor=actor, tier_input=payload)
    await invalidate_namespace("admin:tiers")
    return result


@router.get("", response_model=PaginatedResponse[TierRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:tiers:list",
    resource_id_name=["page", "items_per_page"],
    namespace="admin:tiers",
    expiration=60,
)
async def list_tiers(
    request: Request,
    actor: Annotated[Actor, Depends(require_permission("tier:read"))],
    service: TierServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
) -> PaginatedResponse[TierRead]:
    return await service.get_all_tiers(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
    )


@router.get("/{tier_id}", response_model=TierRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:tiers:detail",
    resource_id_name="tier_id",
    expiration=60,
)
async def get_tier(
    request: Request,
    tier_id: int,
    actor: Annotated[Actor, Depends(require_permission("tier:read"))],
    service: TierServiceDependency,
) -> TierRead:
    return await service.get_tier(actor=actor, tier_id=tier_id)


@router.patch("/{tier_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:tiers:detail",
    resource_id_name="tier_id",
    namespaces_to_invalidate=["admin:tiers"],
)
async def update_tier(
    request: Request,
    tier_id: int,
    payload: TierUpdate,
    actor: Annotated[Actor, Depends(require_permission("tier:update"))],
    service: TierServiceDependency,
) -> None:
    await service.update(actor=actor, tier_id=tier_id, tier_input=payload)


@router.delete("/bulk", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_hard_delete_tiers(
    payload: TierBulkDelete,
    actor: SuperuserActorDependency,
    service: TierServiceDependency,
) -> None:
    await service.bulk_hard_delete(actor=actor, tier_ids=payload.ids)
    await invalidate_namespace("admin:tiers")


@router.delete("/{tier_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:tiers:detail",
    resource_id_name="tier_id",
    namespaces_to_invalidate=["admin:tiers"],
)
async def hard_delete_tier(
    request: Request,
    tier_id: int,
    actor: SuperuserActorDependency,
    service: TierServiceDependency,
) -> None:
    await service.hard_delete(actor=actor, tier_id=tier_id)
