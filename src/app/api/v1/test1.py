import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db.database import async_get_db
from ...core.notifications.service import notify_users_near_event_using_alert_center_radius
from ...core.utils import queue

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["tests"])


class NearbyAlertCenterNotificationTestRequest(BaseModel):
    event_longitude: float = Field(...)
    event_latitude: float = Field(...)
    notification_title: str = Field(...)
    notification_body: str = Field(...)
    notification_data: dict[str, str] = Field(default_factory=dict)
    notification_feature: str = Field(default="nearby_report_alerts")
    radius_in_meters: int = Field(default=3_000)
    excluded_user_id: int | None = Field(default=None)


@router.post("/notify_nearby/enqueue", status_code=202)
async def enqueue_notify_nearby_alert_center(
    payload: NearbyAlertCenterNotificationTestRequest,
) -> dict[str, Any]:
    try:
        await queue.pool.enqueue_job(
            "notify_nearby_alert_center_task",
            event_longitude=payload.event_longitude,
            event_latitude=payload.event_latitude,
            notification_title=payload.notification_title,
            notification_body=payload.notification_body,
            notification_data=payload.notification_data,
            notification_feature=payload.notification_feature,
            radius_in_meters=payload.radius_in_meters,
            excluded_user_id=payload.excluded_user_id,
        )
    except Exception as error:
        LOGGER.warning(f"Failed to enqueue notify_nearby_alert_center_task: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue notification job.",
        )

    return {"message": "Enqueued notify_nearby_alert_center_task"}


@router.post("/notify_nearby/run_now", status_code=status.HTTP_200_OK)
async def run_notify_nearby_alert_center_now(
    payload: NearbyAlertCenterNotificationTestRequest,
    database_session: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, Any]:
    try:
        await notify_users_near_event_using_alert_center_radius(
            database_session,
            event_longitude=payload.event_longitude,
            event_latitude=payload.event_latitude,
            notification_title=payload.notification_title,
            notification_body=payload.notification_body,
            notification_data=payload.notification_data,
            notification_feature=payload.notification_feature,
            radius_in_meters=payload.radius_in_meters,
            excluded_user_id=payload.excluded_user_id,
        )
    except Exception as error:
        LOGGER.warning(f"run_now notify failed: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Notification run failed.",
        )

    return {"message": "Notification executed"}
