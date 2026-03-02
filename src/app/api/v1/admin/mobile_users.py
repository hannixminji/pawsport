from typing import Annotated

from fastapi import Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter
from app.api.dependencies import get_current_admin_actor, get_current_superuser_actor
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache
from app.schemas.mobile_user import MobileUserPasswordUpdate, MobileUserRead, MobileUserUpdate
from app.services.mobile_user_service import MobileUserService

router = CSRFProtectedRouter(prefix="/users", tags=["Mobile Users"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> MobileUserService:
    return MobileUserService(db=db)


MobileUserServiceDependency = Annotated[MobileUserService, Depends(get_service)]
SuperuserActorDependency = Annotated[Actor, Depends(get_current_superuser_actor)]
AdminActorDependency = Annotated[Actor, Depends(get_current_admin_actor)]


@router.post("/search", response_model=PaginatedResponse[MobileUserRead], status_code=status.HTTP_200_OK)
async def search_mobile_users(
    search_request: SearchRequest,
    actor: AdminActorDependency,
    service: MobileUserServiceDependency,
    user_id: Annotated[int | None, Query(alias="userId")] = None,
) -> PaginatedResponse[MobileUserRead]:
    return await service.search(actor=actor, search_request=search_request, user_id=user_id)


@router.get("", response_model=PaginatedResponse[MobileUserRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="mobile_users:page_{page}:size_{items_per_page}",
    resource_id_name="page",
    expiration=60,
)
async def list_mobile_users(
    request: Request,
    actor: AdminActorDependency,
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
@cache(key_prefix="mobile_user", resource_id_name="user_id", expiration=60)
async def get_mobile_user(
    request: Request,
    user_id: int,
    actor: AdminActorDependency,
    service: MobileUserServiceDependency,
) -> MobileUserRead:
    return await service.get_mobile_user(actor=actor, user_id=user_id)


@router.patch("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="mobile_user",
    resource_id_name="user_id",
    pattern_to_invalidate_extra=["mobile_users:*"],
)
async def update_mobile_user(
    request: Request,
    user_id: int,
    payload: MobileUserUpdate,
    actor: AdminActorDependency,
    service: MobileUserServiceDependency,
) -> None:
    await service.update(actor=actor, user_id=user_id, user_input=payload)


@router.patch("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def update_mobile_user_password(
    request: Request,
    user_id: int,
    payload: MobileUserPasswordUpdate,
    actor: AdminActorDependency,
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
    key_prefix="mobile_user",
    resource_id_name="user_id",
    pattern_to_invalidate_extra=["mobile_users:*"],
)
async def update_mobile_user_tier(
    request: Request,
    user_id: int,
    actor: AdminActorDependency,
    service: MobileUserServiceDependency,
    tier_id: Annotated[int | None, Query(alias="tierId")] = None,
) -> None:
    await service.update_tier(actor=actor, user_id=user_id, tier_id=tier_id)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="mobile_user",
    resource_id_name="user_id",
    pattern_to_invalidate_extra=["mobile_users:*"],
)
async def soft_delete_mobile_user(
    request: Request,
    user_id: int,
    actor: AdminActorDependency,
    service: MobileUserServiceDependency,
) -> None:
    await service.soft_delete(actor=actor, user_id=user_id)


@router.delete("/{user_id}/hard", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="mobile_user",
    resource_id_name="user_id",
    pattern_to_invalidate_extra=["mobile_users:*"],
)
async def hard_delete_mobile_user(
    request: Request,
    user_id: int,
    actor: SuperuserActorDependency,
    service: MobileUserServiceDependency,
) -> None:
    await service.hard_delete(actor=actor, user_id=user_id)
