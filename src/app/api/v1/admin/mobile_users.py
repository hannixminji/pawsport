from typing import Annotated

from fastapi import Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter, csrf_exempt
from app.api.dependencies import get_current_superuser_actor, require_permission
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.mobile_user import (
    MobileUserAccountStatusUpdate,
    MobileUserCreate,
    MobileUserPasswordUpdate,
    MobileUserRead,
    MobileUserUpdate,
)
from app.services.mobile_user_service import MobileUserService

router = CSRFProtectedRouter(prefix="/mobile-users", tags=["Mobile Users"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> MobileUserService:
    return MobileUserService(db=db)


MobileUserServiceDependency = Annotated[MobileUserService, Depends(get_service)]
SuperuserActorDependency = Annotated[Actor, Depends(get_current_superuser_actor)]


@csrf_exempt
@router.post("/search", response_model=PaginatedResponse[MobileUserRead], status_code=status.HTTP_200_OK)
async def search_mobile_users(
    search_request: SearchRequest,
    actor: Annotated[Actor, Depends(require_permission("mobile_user:search"))],
    service: MobileUserServiceDependency,
    user_id: Annotated[int | None, Query(alias="userId")] = None,
) -> PaginatedResponse[MobileUserRead]:
    return await service.search(actor=actor, search_request=search_request, user_id=user_id)


@router.post("/{user_id}/email/verification", status_code=status.HTTP_204_NO_CONTENT)
async def send_verification_email(
    request: Request,
    user_id: int,
    actor: Annotated[Actor, Depends(require_permission("mobile_user:send_verification_email"))],
    service: MobileUserServiceDependency,
) -> None:
    await service.send_verification_email(actor=actor, user_id=user_id)


@router.post("", response_model=MobileUserRead, status_code=status.HTTP_201_CREATED)
async def create_mobile_user(
    request: Request,
    payload: MobileUserCreate,
    actor: Annotated[Actor, Depends(require_permission("mobile_user:create"))],
    service: MobileUserServiceDependency,
) -> MobileUserRead:
    result = await service.create(actor=actor, user_input=payload)
    await invalidate_namespace("mobile-users")
    return result


@router.get("", response_model=PaginatedResponse[MobileUserRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:mobile-users:list",
    resource_id_name=["page", "items_per_page"],
    namespace="mobile-users",
    expiration=60,
)
async def list_mobile_users(
    request: Request,
    actor: Annotated[Actor, Depends(require_permission("mobile_user:read"))],
    service: MobileUserServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
) -> PaginatedResponse[MobileUserRead]:
    return await service.get_all_mobile_users(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
    )


@router.get("/{user_id}", response_model=MobileUserRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:mobile-users:detail",
    resource_id_name="user_id",
    expiration=60,
)
async def get_mobile_user(
    request: Request,
    user_id: int,
    actor: Annotated[Actor, Depends(require_permission("mobile_user:read"))],
    service: MobileUserServiceDependency,
) -> MobileUserRead:
    return await service.get_mobile_user(actor=actor, user_id=user_id)


@router.patch("/{user_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:mobile-users:detail",
    resource_id_name="user_id",
    namespaces_to_invalidate=["mobile-users"],
)
async def soft_delete_mobile_user(
    request: Request,
    user_id: int,
    actor: Annotated[Actor, Depends(require_permission("mobile_user:soft_delete"))],
    service: MobileUserServiceDependency,
) -> None:
    await service.soft_delete(actor=actor, user_id=user_id)


@router.patch("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def update_mobile_user_password(
    request: Request,
    user_id: int,
    payload: MobileUserPasswordUpdate,
    actor: Annotated[Actor, Depends(require_permission("mobile_user:update_password"))],
    service: MobileUserServiceDependency,
) -> None:
    await service.change_password(
        actor=actor,
        user_id=user_id,
        current_password=payload.current_password.get_secret_value(),
        new_password=payload.new_password.get_secret_value(),
    )


@router.patch("/{user_id}/tier", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:mobile-users:detail",
    resource_id_name="user_id",
    namespaces_to_invalidate=["mobile-users"],
)
async def update_mobile_user_tier(
    request: Request,
    user_id: int,
    actor: Annotated[Actor, Depends(require_permission("mobile_user:update_tier"))],
    service: MobileUserServiceDependency,
    tier_id: Annotated[int | None, Query(alias="tierId")] = None,
) -> None:
    await service.update_tier(actor=actor, user_id=user_id, tier_id=tier_id)


@router.patch("/{user_id}/account-status", status_code=status.HTTP_204_NO_CONTENT)  # ← here
@cache(
    key_prefix="admin:mobile-users:detail",
    resource_id_name="user_id",
    namespaces_to_invalidate=["mobile-users"],
)
async def update_mobile_user_account_status(
    request: Request,
    user_id: int,
    payload: MobileUserAccountStatusUpdate,
    actor: Annotated[Actor, Depends(require_permission("mobile_user:update_account_status"))],
    service: MobileUserServiceDependency,
) -> None:
    await service.update_account_status(actor=actor, user_id=user_id, user_input=payload)


@router.patch("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:mobile-users:detail",
    resource_id_name="user_id",
    namespaces_to_invalidate=["mobile-users"],
)
async def update_mobile_user(
    request: Request,
    user_id: int,
    payload: MobileUserUpdate,
    actor: Annotated[Actor, Depends(require_permission("mobile_user:update"))],
    service: MobileUserServiceDependency,
) -> None:
    await service.update(actor=actor, user_id=user_id, user_input=payload)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:mobile-users:detail",
    resource_id_name="user_id",
    namespaces_to_invalidate=["mobile-users"],
)
async def hard_delete_mobile_user(
    request: Request,
    user_id: int,
    actor: SuperuserActorDependency,
    service: MobileUserServiceDependency,
) -> None:
    await service.hard_delete(actor=actor, user_id=user_id)
