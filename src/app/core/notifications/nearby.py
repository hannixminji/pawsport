from __future__ import annotations

from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import cast, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_preference import NotificationPreference
from app.models.push_token import PushToken
from app.models.user import User
from app.schemas.notification_preference import NotificationFeature

DEFAULT_RADIUS_IN_METERS = 3_000


def build_event_geography_point(
    *,
    event_longitude: float,
    event_latitude: float,
) -> Any:
    geometry_point = func.ST_SetSRID(func.ST_MakePoint(event_longitude, event_latitude), 4326)
    geography_point = cast(geometry_point, Geography(geometry_type="POINT", srid=4326))
    return geography_point


async def fetch_push_tokens_within_radius_of_user_alert_center(
    database_session: AsyncSession,
    *,
    event_longitude: float,
    event_latitude: float,
    radius_in_meters: int = DEFAULT_RADIUS_IN_METERS,
    notification_feature: NotificationFeature = NotificationFeature.NEARBY_REPORT_ALERTS,
    excluded_user_id: int | None = None,
) -> list[str]:
    event_geography_point = build_event_geography_point(
        event_longitude=event_longitude,
        event_latitude=event_latitude,
    )

    query = (
        select(PushToken.token)
        .join(User, User.id == PushToken.user_id)
        .where(
            User.is_deleted.is_(False),
            User.alert_center_geog.is_not(None),
            func.ST_DWithin(User.alert_center_geog, event_geography_point, radius_in_meters),
            ~exists(
                select(1).where(
                    NotificationPreference.user_id == User.id,
                    NotificationPreference.feature == notification_feature.value,
                    NotificationPreference.is_enabled.is_(False),
                )
            ),
        )
    )

    if excluded_user_id is not None:
        query = query.where(User.id != excluded_user_id)

    result = await database_session.execute(query)
    tokens = result.scalars().all()
    return list(tokens)
