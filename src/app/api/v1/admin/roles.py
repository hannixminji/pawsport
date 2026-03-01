from typing import Annotated

from fastapi import Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter
from app.api.dependencies import get_current_superuser_actor
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache
from app.schemas.admin_role import (
    AdminRoleAssignPermissions,
    AdminRoleBulkDelete,
    AdminRoleCreate,
    AdminRoleRead,
    AdminRoleReadWithPermissions,
    AdminRoleUpdate,
)
from app.services.admin_role_service import AdminRoleService

router = CSRFProtectedRouter(prefix="/roles", tags=["Admin Roles"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> AdminRoleService:
    return AdminRoleService(db=db)


AdminRoleServiceDependency = Annotated[AdminRoleService, Depends(get_service)]
SuperuserActorDependency = Annotated[Actor, Depends(get_current_superuser_actor)]


@router.post("", response_model=AdminRoleRead, status_code=status.HTTP_201_CREATED)
async def create_role(
    request: Request,
    payload: AdminRoleCreate,
    actor: SuperuserActorDependency,
    service: AdminRoleServiceDependency,
) -> AdminRoleRead:
    return await service.create(actor=actor, role_input=payload)


@router.post("/search", response_model=PaginatedResponse[AdminRoleRead], status_code=status.HTTP_200_OK)
async def search_roles(
    search_request: SearchRequest,
    actor: SuperuserActorDependency,
    service: AdminRoleServiceDependency,
) -> PaginatedResponse[AdminRoleRead]:
    return await service.search(actor=actor, search_request=search_request)


@router.get("", response_model=PaginatedResponse[AdminRoleRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin_roles:page_{page}:size_{items_per_page}",
    resource_id_name="page",
    expiration=60,
)
async def list_roles(
    request: Request,
    actor: SuperuserActorDependency,
    service: AdminRoleServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
) -> PaginatedResponse[AdminRoleRead]:
    return await service.get_all_roles(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
    )


@router.get("/{role_id}", response_model=AdminRoleRead, status_code=status.HTTP_200_OK)
@cache(key_prefix="admin_role", resource_id_name="role_id", expiration=60)
async def get_role(
    request: Request,
    role_id: int,
    actor: SuperuserActorDependency,
    service: AdminRoleServiceDependency,
) -> AdminRoleRead:
    return await service.get_role(actor=actor, role_id=role_id)


@router.get("/{role_id}/permissions", response_model=AdminRoleReadWithPermissions, status_code=status.HTTP_200_OK)
@cache(key_prefix="admin_role_with_permissions", resource_id_name="role_id", expiration=60)
async def get_role_with_permissions(
    request: Request,
    role_id: int,
    actor: SuperuserActorDependency,
    service: AdminRoleServiceDependency,
) -> AdminRoleReadWithPermissions:
    return await service.get_role_with_permissions(actor=actor, role_id=role_id)


@router.patch("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin_role",
    resource_id_name="role_id",
    pattern_to_invalidate_extra=["admin_roles:*"],
)
async def update_role(
    request: Request,
    role_id: int,
    payload: AdminRoleUpdate,
    actor: SuperuserActorDependency,
    service: AdminRoleServiceDependency,
) -> None:
    await service.update(actor=actor, role_id=role_id, role_input=payload)


@router.put("/{role_id}/permissions", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin_role_with_permissions",
    resource_id_name="role_id",
    pattern_to_invalidate_extra=["admin_roles:*"],
)
async def assign_permissions(
    request: Request,
    role_id: int,
    payload: AdminRoleAssignPermissions,
    actor: SuperuserActorDependency,
    service: AdminRoleServiceDependency,
) -> None:
    await service.assign_permissions(actor=actor, role_id=role_id, permission_ids=payload.ids)


@router.delete("/{role_id}/permissions", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin_role_with_permissions",
    resource_id_name="role_id",
    pattern_to_invalidate_extra=["admin_roles:*"],
)
async def remove_all_permissions(
    request: Request,
    role_id: int,
    actor: SuperuserActorDependency,
    service: AdminRoleServiceDependency,
) -> None:
    await service.remove_all_permissions(actor=actor, role_id=role_id)


@router.delete("/{role_id}/hard", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin_role",
    resource_id_name="role_id",
    pattern_to_invalidate_extra=["admin_roles:*"],
)
async def hard_delete_role(
    request: Request,
    role_id: int,
    actor: SuperuserActorDependency,
    service: AdminRoleServiceDependency,
) -> None:
    await service.hard_delete(actor=actor, role_id=role_id)


@router.delete("/hard", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_hard_delete_roles(
    payload: AdminRoleBulkDelete,
    actor: SuperuserActorDependency,
    service: AdminRoleServiceDependency,
) -> None:
    await service.bulk_hard_delete(actor=actor, role_ids=payload.ids)
