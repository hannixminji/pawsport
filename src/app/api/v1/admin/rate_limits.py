from typing import Annotated

from fastapi import Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter, csrf_exempt
from app.api.dependencies import get_current_superuser_actor, require_permission
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.rate_limit import RateLimitBulkDelete, RateLimitCreate, RateLimitRead, RateLimitUpdate
from app.services.rate_limit_service import RateLimitService

router = CSRFProtectedRouter(prefix="/rate-limits", tags=["Rate Limits"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> RateLimitService:
    return RateLimitService(db=db)


RateLimitServiceDependency = Annotated[RateLimitService, Depends(get_service)]
SuperuserActorDependency = Annotated[Actor, Depends(get_current_superuser_actor)]


@csrf_exempt
@router.post("/search", response_model=PaginatedResponse[RateLimitRead], status_code=status.HTTP_200_OK)
async def search_rate_limits(
    search_request: SearchRequest,
    actor: Annotated[Actor, Depends(require_permission("rate_limit:search"))],
    service: RateLimitServiceDependency,
    tier_name: Annotated[str | None, Query(alias="tierName")] = None,
) -> PaginatedResponse[RateLimitRead]:
    return await service.search(actor=actor, search_request=search_request, tier_name=tier_name)


@router.post("/{tier_name}", response_model=RateLimitRead, status_code=status.HTTP_201_CREATED)
async def create_rate_limit(
    request: Request,
    tier_name: str,
    payload: RateLimitCreate,
    actor: Annotated[Actor, Depends(require_permission("rate_limit:create"))],
    service: RateLimitServiceDependency,
) -> RateLimitRead:
    result = await service.create(actor=actor, tier_name=tier_name, rate_limit_input=payload)
    await invalidate_namespace("admin:rate-limits")
    return result


@router.get("", response_model=PaginatedResponse[RateLimitRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:rate-limits:list",
    resource_id_name=["page", "items_per_page", "tier_name"],
    namespace="admin:rate-limits",
    expiration=60,
)
async def list_rate_limits(
    request: Request,
    actor: Annotated[Actor, Depends(require_permission("rate_limit:read"))],
    service: RateLimitServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
    tier_name: Annotated[str | None, Query(alias="tierName")] = None,
) -> PaginatedResponse[RateLimitRead]:
    return await service.get_rate_limits(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
        tier_name=tier_name,
    )


@router.get("/{rate_limit_id}", response_model=RateLimitRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:rate-limits:detail",
    resource_id_name="rate_limit_id",
    expiration=60,
)
async def get_rate_limit(
    request: Request,
    rate_limit_id: int,
    actor: Annotated[Actor, Depends(require_permission("rate_limit:read"))],
    service: RateLimitServiceDependency,
) -> RateLimitRead:
    return await service.get_rate_limit(actor=actor, rate_limit_id=rate_limit_id)


@router.patch("/{rate_limit_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:rate-limits:detail",
    resource_id_name="rate_limit_id",
    namespaces_to_invalidate=["admin:rate-limits"],
)
async def update_rate_limit(
    request: Request,
    rate_limit_id: int,
    payload: RateLimitUpdate,
    actor: Annotated[Actor, Depends(require_permission("rate_limit:update"))],
    service: RateLimitServiceDependency,
) -> None:
    await service.update(actor=actor, rate_limit_id=rate_limit_id, rate_limit_input=payload)


@router.delete("/bulk", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_hard_delete_rate_limits(
    payload: RateLimitBulkDelete,
    actor: SuperuserActorDependency,
    service: RateLimitServiceDependency,
) -> None:
    await service.bulk_hard_delete(actor=actor, rate_limit_ids=payload.ids)
    await invalidate_namespace("admin:rate-limits")


@router.delete("/{rate_limit_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:rate-limits:detail",
    resource_id_name="rate_limit_id",
    namespaces_to_invalidate=["admin:rate-limits"],
)
async def hard_delete_rate_limit(
    request: Request,
    rate_limit_id: int,
    actor: SuperuserActorDependency,
    service: RateLimitServiceDependency,
) -> None:
    await service.hard_delete(actor=actor, rate_limit_id=rate_limit_id)
