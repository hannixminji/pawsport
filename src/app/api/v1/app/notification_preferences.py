from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import rate_limiter_dependency
from app.core.db.database import async_get_db
from app.core.schemas import Actor
from app.core.utils.cache import cache
from app.schemas.notification_preference import NotificationPreferenceRead, NotificationPreferenceUpsert
from app.services.notification_preference_service import NotificationPreferenceService

router = APIRouter(prefix="/notification-preferences", tags=["Notification Preferences"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> NotificationPreferenceService:
    return NotificationPreferenceService(db=db)


NotificationPreferenceServiceDependency = Annotated[NotificationPreferenceService, Depends(get_service)]
ActorDependency = Annotated[Actor, Depends(rate_limiter_dependency)]


@router.get("", response_model=NotificationPreferenceRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:notification-preferences:detail",
    resource_id_name="actor.id",
    expiration=60,
)
async def get_notification_preference(
    request: Request,
    actor: ActorDependency,
    service: NotificationPreferenceServiceDependency,
) -> NotificationPreferenceRead:
    return await service.get_preference(actor=actor, user_id=actor.id)


@router.put("", response_model=NotificationPreferenceRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:notification-preferences:detail",
    resource_id_name="actor.id",
)
async def upsert_notification_preference(
    request: Request,
    payload: NotificationPreferenceUpsert,
    actor: ActorDependency,
    service: NotificationPreferenceServiceDependency,
) -> NotificationPreferenceRead:
    return await service.upsert(actor=actor, user_id=actor.id, preference_input=payload)
