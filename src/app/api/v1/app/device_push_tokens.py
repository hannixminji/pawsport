from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import rate_limiter_dependency
from app.core.db.database import async_get_db
from app.core.schemas import Actor
from app.schemas.device_push_token import DevicePushTokenUpsert
from app.services.device_push_token_service import DevicePushTokenService

router = APIRouter(prefix="/device-push-tokens", tags=["Device Push Tokens"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> DevicePushTokenService:
    return DevicePushTokenService(db=db)


DevicePushTokenServiceDependency = Annotated[DevicePushTokenService, Depends(get_service)]
ActorDependency = Annotated[Actor, Depends(rate_limiter_dependency)]


@router.put("", status_code=status.HTTP_204_NO_CONTENT)
async def upsert_device_push_token(
    request: Request,
    payload: DevicePushTokenUpsert,
    actor: ActorDependency,
    service: DevicePushTokenServiceDependency,
) -> None:
    await service.upsert(actor=actor, user_id=actor.id, token_input=payload)


@router.delete("/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device_push_token(
    request: Request,
    token: str,
    actor: ActorDependency,
    service: DevicePushTokenServiceDependency,
) -> None:
    await service.hard_delete(actor=actor, user_id=actor.id, token=token)
