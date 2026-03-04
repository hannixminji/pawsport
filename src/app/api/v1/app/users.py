from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import rate_limiter_dependency
from app.core.db.database import async_get_db
from app.core.schemas import Actor
from app.core.utils.cache import cache
from app.schemas.mobile_user import MobileUserPasswordUpdate, MobileUserRead, MobileUserUpdate
from app.services.mobile_user_service import MobileUserService

router = APIRouter(prefix="/mobile-users", tags=["Mobile Users"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> MobileUserService:
    return MobileUserService(db=db)


MobileUserServiceDependency = Annotated[MobileUserService, Depends(get_service)]
ActorDependency = Annotated[Actor, Depends(rate_limiter_dependency)]


@router.get("/{user_id}", response_model=MobileUserRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:mobile-users:detail",
    resource_id_name="user_id",
    expiration=60,
)
async def get_mobile_user(
    request: Request,
    user_id: int,
    actor: ActorDependency,
    service: MobileUserServiceDependency,
) -> MobileUserRead:
    return await service.get_mobile_user(actor=actor, user_id=user_id)


@router.patch("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def update_mobile_user_password(
    request: Request,
    user_id: int,
    payload: MobileUserPasswordUpdate,
    actor: ActorDependency,
    service: MobileUserServiceDependency,
) -> None:
    await service.change_password(
        actor=actor,
        user_id=user_id,
        current_password=payload.current_password.get_secret_value(),
        new_password=payload.new_password.get_secret_value(),
    )


@router.patch("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="app:mobile-users:detail",
    resource_id_name="user_id",
    namespaces_to_invalidate=["app:mobile-users"],
)
async def update_mobile_user(
    request: Request,
    user_id: int,
    payload: MobileUserUpdate,
    actor: ActorDependency,
    service: MobileUserServiceDependency,
) -> None:
    await service.update(actor=actor, user_id=user_id, user_input=payload)
