import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.dependencies import get_authenticated_user
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import ForbiddenException, NotFoundException
from ...core.utils.cache import cache
from ...models.notification_preference import NotificationPreference as NotificationPreferenceModel
from ...models.user import User
from ...schemas.notification_preference import NotificationPreferenceCreate, NotificationPreferenceRead
from ...schemas.user import UserRead

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["notification_preferences"])


@router.get(
    "/{username}/notification_preferences",
    response_model=list[NotificationPreferenceRead],
    status_code=status.HTTP_200_OK,
)
@cache(
    key_prefix="{username}_notification_preferences",
    resource_id_name="username",
    expiration=60,
)
async def read_notification_preferences(
    request: Request,
    username: str,
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> list[NotificationPreferenceRead]:
    db_user_id = (
        await db.execute(
            select(User.id)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    if current_user.id != db_user_id:
        raise ForbiddenException()

    db_notification_preferences = (
        await db.execute(
            select(NotificationPreferenceModel)
            .where(NotificationPreferenceModel.user_id == current_user.id)
            .order_by(NotificationPreferenceModel.feature.asc())
        )
    ).scalars().all()

    return [
        NotificationPreferenceRead.model_validate(notification_preference)
        for notification_preference in db_notification_preferences
    ]


@router.post(
    "/{username}/notification_preferences",
    status_code=status.HTTP_200_OK,
)
async def upsert_notification_preference(
    request: Request,
    username: str,
    values: NotificationPreferenceCreate,
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    db_user_id = (
        await db.execute(
            select(User.id).where(
                User.username == username,
                ~User.is_deleted,
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    if current_user.id != db_user_id:
        raise ForbiddenException()

    now = datetime.now(UTC)
    feature_str = str(values.feature)

    try:
        stmt = (
            insert(NotificationPreferenceModel)
            .values(
                user_id=db_user_id,
                feature=feature_str,
                is_enabled=values.is_enabled,
                created_at=now,
                updated_at=now
            )
            .on_conflict_do_update(
                index_elements=[
                    NotificationPreferenceModel.user_id,
                    NotificationPreferenceModel.feature
                ],
                set_={
                    "is_enabled": values.is_enabled,
                    "updated_at": now
                }
            )
        )

        await db.execute(stmt)
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while saving the notification preference. Please try again later.",
        )

    return {"message": "Notification preference updated"}
