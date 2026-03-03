from typing import Annotated

from fastapi import Depends, Query, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter
from app.api.dependencies import get_current_superuser_actor, get_redis_client
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.admin_permission import (
    AdminPermissionBulkDelete,
    AdminPermissionCreate,
    AdminPermissionRead,
    AdminPermissionUpdate,
)
from app.services.admin_permission_service import AdminPermissionService

router = CSRFProtectedRouter(prefix="/permissions", tags=["Admin Permissions"])


async def get_service(
    db: AsyncSession = Depends(async_get_db),
    redis: Redis = Depends(get_redis_client),
) -> AdminPermissionService:
    return AdminPermissionService(db=db, redis=redis)


AdminPermissionServiceDependency = Annotated[AdminPermissionService, Depends(get_service)]
SuperuserActorDependency = Annotated[Actor, Depends(get_current_superuser_actor)]


@router.post("", response_model=AdminPermissionRead, status_code=status.HTTP_201_CREATED)
async def create_permission(
    request: Request,
    payload: AdminPermissionCreate,
    actor: SuperuserActorDependency,
    service: AdminPermissionServiceDependency,
) -> AdminPermissionRead:
    result = await service.create(actor=actor, permission_input=payload)
    await invalidate_namespace("admin:permissions")
    return result


@router.post("/search", response_model=PaginatedResponse[AdminPermissionRead], status_code=status.HTTP_200_OK)
async def search_permissions(
    search_request: SearchRequest,
    actor: SuperuserActorDependency,
    service: AdminPermissionServiceDependency,
) -> PaginatedResponse[AdminPermissionRead]:
    return await service.search(actor=actor, search_request=search_request)


@router.get("", response_model=PaginatedResponse[AdminPermissionRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:permissions:list",
    resource_id_name=["page", "items_per_page"],
    namespace="admin:permissions",
    expiration=60,
)
async def list_permissions(
    request: Request,
    actor: SuperuserActorDependency,
    service: AdminPermissionServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
) -> PaginatedResponse[AdminPermissionRead]:
    return await service.get_all_permissions(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
    )


@router.get("/{permission_id}", response_model=AdminPermissionRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:permissions:detail",
    resource_id_name="permission_id",
    expiration=60,
)
async def get_permission(
    request: Request,
    permission_id: int,
    actor: SuperuserActorDependency,
    service: AdminPermissionServiceDependency,
) -> AdminPermissionRead:
    return await service.get_permission(actor=actor, permission_id=permission_id)


@router.patch("/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:permissions:detail",
    resource_id_name="permission_id",
    namespaces_to_invalidate=["admin:permissions"],
)
async def update_permission(
    request: Request,
    permission_id: int,
    payload: AdminPermissionUpdate,
    actor: SuperuserActorDependency,
    service: AdminPermissionServiceDependency,
) -> None:
    await service.update(actor=actor, permission_id=permission_id, permission_input=payload)


@router.delete("/bulk", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_hard_delete_permissions(
    payload: AdminPermissionBulkDelete,
    actor: SuperuserActorDependency,
    service: AdminPermissionServiceDependency,
) -> None:
    await service.bulk_hard_delete(actor=actor, permission_ids=payload.ids)
    await invalidate_namespace("admin:permissions")


@router.delete("/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:permissions:detail",
    resource_id_name="permission_id",
    namespaces_to_invalidate=["admin:permissions"],
)
async def hard_delete_permission(
    request: Request,
    permission_id: int,
    actor: SuperuserActorDependency,
    service: AdminPermissionServiceDependency,
) -> None:
    await service.hard_delete(actor=actor, permission_id=permission_id)
