from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.push_token import PushToken
from app.schemas.notification_preference import NotificationFeature

from .nearby import fetch_push_tokens_within_radius_of_user_alert_center
from .sender_fcm import send_fcm_multicast_notifications_in_chunks


async def notify_users_near_event_using_alert_center_radius(
    database_session: AsyncSession,
    *,
    event_longitude: float,
    event_latitude: float,
    notification_title: str,
    notification_body: str,
    notification_data: dict[str, str],
    notification_feature: NotificationFeature = NotificationFeature.NEARBY_REPORT_ALERTS,
    radius_in_meters: int = 3_000,
    excluded_user_id: int | None = None,
) -> None:
    registration_tokens = await fetch_push_tokens_within_radius_of_user_alert_center(
        database_session,
        event_longitude=event_longitude,
        event_latitude=event_latitude,
        radius_in_meters=radius_in_meters,
        notification_feature=notification_feature,
        excluded_user_id=excluded_user_id,
    )

    if not registration_tokens:
        return

    invalid_registration_tokens = await send_fcm_multicast_notifications_in_chunks(
        registration_tokens=registration_tokens,
        notification_title=notification_title,
        notification_body=notification_body,
        notification_data=notification_data,
    )

    if invalid_registration_tokens:
        await database_session.execute(
            delete(PushToken)
            .where(PushToken.token.in_(invalid_registration_tokens))
        )
