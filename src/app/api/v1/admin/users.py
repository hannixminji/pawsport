from typing import Annotated

from fastapi import Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter
from app.api.dependencies import get_current_admin_actor, get_current_superuser_actor
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache
from app.schemas.admin_role import AdminRoleRead
from app.schemas.admin_user import (
    AdminUserAssignPermissions,
    AdminUserAssignRoles,
    AdminUserBulkDelete,
    AdminUserCreate,
    AdminUserPasswordUpdate,
    AdminUserRead,
    AdminUserStatusUpdate,
    AdminUserUpdate,
)
from app.services.admin_user_service import AdminUserService

router = CSRFProtectedRouter(prefix="/users", tags=["Admin Users"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> AdminUserService:
    return AdminUserService(db=db)


AdminUserServiceDependency = Annotated[AdminUserService, Depends(get_service)]
SuperuserActorDependency = Annotated[Actor, Depends(get_current_superuser_actor)]
AdminActorDependency = Annotated[Actor, Depends(get_current_admin_actor)]


@router.post("", response_model=AdminUserRead, status_code=status.HTTP_201_CREATED)
async def create_admin_user(
    request: Request,
    payload: AdminUserCreate,
    actor: SuperuserActorDependency,
    service: AdminUserServiceDependency,
) -> AdminUserRead:
    return await service.create(actor=actor, user_input=payload)


@router.post("/search", response_model=PaginatedResponse[AdminUserRead], status_code=status.HTTP_200_OK)
async def search_admin_users(
    search_request: SearchRequest,
    actor: SuperuserActorDependency,
    service: AdminUserServiceDependency,
) -> PaginatedResponse[AdminUserRead]:
    return await service.search(actor=actor, search_request=search_request)


@router.get("", response_model=PaginatedResponse[AdminUserRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin_users:page_{page}:size_{items_per_page}",
    resource_id_name="page",
    expiration=60,
)
async def list_admin_users(
    request: Request,
    actor: SuperuserActorDependency,
    service: AdminUserServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
) -> PaginatedResponse[AdminUserRead]:
    return await service.get_all_admin_users(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
    )


@router.get("/{user_id}/roles", response_model=PaginatedResponse[AdminRoleRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin_user_roles",
    resource_id_name="user_id",
    expiration=60,
)
async def get_admin_user_roles(
    request: Request,
    user_id: int,
    actor: SuperuserActorDependency,
    service: AdminUserServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
) -> PaginatedResponse[AdminRoleRead]:
    return await service.get_admin_user_roles(
        actor=actor,
        user_id=user_id,
        page=page,
        items_per_page=items_per_page,
    )


@router.get("/{user_id}", response_model=AdminUserRead, status_code=status.HTTP_200_OK)
@cache(key_prefix="admin_user", resource_id_name="user_id", expiration=60)
async def get_admin_user(
    request: Request,
    user_id: int,
    actor: SuperuserActorDependency,
    service: AdminUserServiceDependency,
) -> AdminUserRead:
    return await service.get_admin_user(actor=actor, user_id=user_id)


@router.patch("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin_user",
    resource_id_name="user_id",
    pattern_to_invalidate_extra=["admin_users:*"],
)
async def update_admin_user(
    request: Request,
    user_id: int,
    payload: AdminUserUpdate,
    actor: SuperuserActorDependency,
    service: AdminUserServiceDependency,
) -> None:
    await service.update(actor=actor, user_id=user_id, user_input=payload)


@router.patch("/{user_id}/status", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin_user",
    resource_id_name="user_id",
    pattern_to_invalidate_extra=["admin_users:*"],
)
async def update_admin_user_status(
    request: Request,
    user_id: int,
    payload: AdminUserStatusUpdate,
    actor: SuperuserActorDependency,
    service: AdminUserServiceDependency,
) -> None:
    await service.update_account_status(actor=actor, user_id=user_id, account_status=payload.account_status)


@router.patch("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def update_admin_user_password(
    request: Request,
    user_id: int,
    payload: AdminUserPasswordUpdate,
    actor: AdminActorDependency,
    service: AdminUserServiceDependency,
) -> None:
    await service.change_password(
        actor=actor,
        user_id=user_id,
        current_password=payload.current_password.get_secret_value(),
        new_password=payload.new_password.get_secret_value(),
    )


@router.put("/{user_id}/roles", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin_user",
    resource_id_name="user_id",
    pattern_to_invalidate_extra=["admin_users:*"],
)
async def assign_roles_to_admin_user(
    request: Request,
    user_id: int,
    payload: AdminUserAssignRoles,
    actor: SuperuserActorDependency,
    service: AdminUserServiceDependency,
) -> None:
    await service.assign_roles(actor=actor, user_id=user_id, role_ids=set(payload.role_ids))


@router.delete("/{user_id}/roles", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin_user",
    resource_id_name="user_id",
    pattern_to_invalidate_extra=["admin_users:*"],
)
async def remove_all_roles_from_admin_user(
    request: Request,
    user_id: int,
    actor: SuperuserActorDependency,
    service: AdminUserServiceDependency,
) -> None:
    await service.remove_all_roles(actor=actor, user_id=user_id)


@router.put("/{user_id}/permissions", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin_user",
    resource_id_name="user_id",
    pattern_to_invalidate_extra=["admin_users:*"],
)
async def assign_direct_permissions_to_admin_user(
    request: Request,
    user_id: int,
    payload: AdminUserAssignPermissions,
    actor: SuperuserActorDependency,
    service: AdminUserServiceDependency,
) -> None:
    await service.assign_direct_permissions(actor=actor, user_id=user_id, permission_ids=set(payload.permission_ids))


@router.delete("/{user_id}/permissions", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin_user",
    resource_id_name="user_id",
    pattern_to_invalidate_extra=["admin_users:*"],
)
async def remove_all_direct_permissions_from_admin_user(
    request: Request,
    user_id: int,
    actor: SuperuserActorDependency,
    service: AdminUserServiceDependency,
) -> None:
    await service.remove_all_direct_permissions(actor=actor, user_id=user_id)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin_user",
    resource_id_name="user_id",
    pattern_to_invalidate_extra=["admin_users:*"],
)
async def soft_delete_admin_user(
    request: Request,
    user_id: int,
    actor: SuperuserActorDependency,
    service: AdminUserServiceDependency,
) -> None:
    await service.soft_delete(actor=actor, user_id=user_id)


@router.delete("/soft", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_soft_delete_admin_users(
    payload: AdminUserBulkDelete,
    actor: SuperuserActorDependency,
    service: AdminUserServiceDependency,
) -> None:
    await service.bulk_soft_delete(actor=actor, user_ids=payload.ids)


@router.delete("/{user_id}/hard", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin_user",
    resource_id_name="user_id",
    pattern_to_invalidate_extra=["admin_users:*"],
)
async def hard_delete_admin_user(
    request: Request,
    user_id: int,
    actor: SuperuserActorDependency,
    service: AdminUserServiceDependency,
) -> None:
    await service.hard_delete(actor=actor, user_id=user_id)


@router.delete("/hard", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_hard_delete_admin_users(
    payload: AdminUserBulkDelete,
    actor: SuperuserActorDependency,
    service: AdminUserServiceDependency,
) -> None:
    await service.bulk_hard_delete(actor=actor, user_ids=payload.ids)
