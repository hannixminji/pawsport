from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter
from app.api.dependencies import get_current_admin_actor
from app.core.db.database import async_get_db
from app.core.schemas import Actor
from app.core.utils.cache import cache
from app.schemas.notification_preference import NotificationPreferenceRead, NotificationPreferenceUpsert
from app.services.notification_preference_service import NotificationPreferenceService

router = CSRFProtectedRouter(prefix="/notification-preferences", tags=["Notification Preferences"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> NotificationPreferenceService:
    return NotificationPreferenceService(db=db)


NotificationPreferenceServiceDependency = Annotated[NotificationPreferenceService, Depends(get_service)]
AdminActorDependency = Annotated[Actor, Depends(get_current_admin_actor)]


@router.get("/{user_id}", response_model=NotificationPreferenceRead, status_code=status.HTTP_200_OK)
@cache(key_prefix="notification_preference", resource_id_name="user_id", expiration=60)
async def get_notification_preference(
    request: Request,
    user_id: int,
    actor: AdminActorDependency,
    service: NotificationPreferenceServiceDependency,
) -> NotificationPreferenceRead:
    return await service.get_preference(actor=actor, user_id=user_id)


@router.put("/{user_id}", response_model=NotificationPreferenceRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="notification_preference",
    resource_id_name="user_id",
    pattern_to_invalidate_extra=["notification_preference:*"],
)
async def upsert_notification_preference(
    request: Request,
    user_id: int,
    payload: NotificationPreferenceUpsert,
    actor: AdminActorDependency,
    service: NotificationPreferenceServiceDependency,
) -> NotificationPreferenceRead:
    return await service.upsert(actor=actor, user_id=user_id, preference_input=payload)
