import logging

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, TEXT
from sqlalchemy.ext.asyncio import AsyncSession

from ..enums import NotificationFeature
from .nearby import fetch_push_tokens_within_radius_of_user_alert_center
from .sender_fcm import send_fcm_multicast_notifications_in_chunks

logger = logging.getLogger(__name__)


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
        logger.debug(
            "No eligible push tokens found within %dm of (%.4f, %.4f) — skipping.",
            radius_in_meters,
            event_latitude,
            event_longitude,
        )
        return

    logger.info(
        "Dispatching '%s' to %d devices within %dm of (%.4f, %.4f).",
        notification_title,
        len(registration_tokens),
        radius_in_meters,
        event_latitude,
        event_longitude,
    )

    invalid_registration_tokens = await send_fcm_multicast_notifications_in_chunks(
        registration_tokens=registration_tokens,
        notification_title=notification_title,
        notification_body=notification_body,
        notification_data=notification_data,
    )

    if not invalid_registration_tokens:
        return

    statement = text(
        """
        DELETE FROM device_push_token
        WHERE token = ANY(:tokens)
        """
    ).bindparams(
        bindparam("tokens", type_=ARRAY(TEXT))
    )

    await database_session.execute(
        statement,
        {"tokens": invalid_registration_tokens},
    )

    logger.info(
        "Purged %d dead FCM tokens from device_push_token.",
        len(invalid_registration_tokens),
    )
