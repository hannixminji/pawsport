import logging
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.device_push_token import DevicePushToken
from ...models.mobile_user import MobileUser
from ...models.notification_preference import NotificationPreference
from ..enums import NotificationFeature, PushTokenPlatform, PushTokenProvider

logger = logging.getLogger(__name__)

DEFAULT_RADIUS_IN_METERS: int = 3_000
MAX_TOKENS_PER_QUERY: int = 10_000


def build_event_geography_point(
    *,
    event_longitude: float,
    event_latitude: float,
) -> Any:
    geometry_point = func.ST_SetSRID(
        func.ST_MakePoint(event_longitude, event_latitude), 4326
    )
    return cast(geometry_point, Geography(geometry_type="POINT", srid=4326))


def _resolve_feature_column(notification_feature: NotificationFeature) -> Any:
    feature_map: dict[NotificationFeature, Any] = {
        NotificationFeature.NEARBY_REPORT_ALERTS: (
            NotificationPreference.nearby_report_alerts_enabled
        ),
    }

    column = feature_map.get(notification_feature)
    if column is None:
        raise ValueError(
            f"No DB column mapped for notification feature: {notification_feature!r}. "
            "Register it in _resolve_feature_column()."
        )
    return column


async def fetch_push_tokens_within_radius_of_user_alert_center(
    database_session: AsyncSession,
    *,
    event_longitude: float,
    event_latitude: float,
    radius_in_meters: int = DEFAULT_RADIUS_IN_METERS,
    notification_feature: NotificationFeature = NotificationFeature.NEARBY_REPORT_ALERTS,
    excluded_user_id: int | None = None,
    limit: int = MAX_TOKENS_PER_QUERY,
) -> list[str]:
    event_geography_point = build_event_geography_point(
        event_longitude=event_longitude,
        event_latitude=event_latitude,
    )

    feature_col = _resolve_feature_column(notification_feature)

    preference_condition = (feature_col.is_(True)) | (NotificationPreference.mobile_user_id.is_(None))

    query = (
        select(DevicePushToken.token)
        .distinct()
        .join(MobileUser, MobileUser.id == DevicePushToken.mobile_user_id)
        .outerjoin(
            NotificationPreference,
            NotificationPreference.mobile_user_id == MobileUser.id,
        )
        .where(
            MobileUser.is_deleted.is_(False),
            func.ST_DWithin(
                MobileUser.nearby_report_alert_location,
                event_geography_point,
                radius_in_meters,
            ),
            preference_condition,
            DevicePushToken.provider == PushTokenProvider.FCM,
            DevicePushToken.platform == PushTokenPlatform.ANDROID,
        )
        .limit(limit)
    )

    if excluded_user_id is not None:
        query = query.where(MobileUser.id != excluded_user_id)

    result = await database_session.execute(query)
    tokens = list(result.scalars().all())

    logger.debug(
        "Fetched %d push tokens within %dm of (%.4f, %.4f)",
        len(tokens),
        radius_in_meters,
        event_latitude,
        event_longitude,
    )

    return tokens
