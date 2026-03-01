import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.enums import ActorType
from ..core.exceptions.authorization_exceptions import ForbiddenError
from ..core.exceptions.db_exceptions import NonTransientDatabaseError, TransientDatabaseError
from ..core.schemas import Actor, PaginatedResponse
from ..core.utils.update import apply_partial_update
from ..models.notification_preference import NotificationPreference
from ..schemas.notification_preference import NotificationPreferenceRead, NotificationPreferenceUpdate

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class NotificationPreferenceService:
    db: AsyncSession

    DEFAULT_PREFERENCES = NotificationPreferenceRead(
        nearby_report_alerts_enabled=True,
        pet_schedule_reminders_enabled=True,
    )

    async def _get_preference_by_user_id(self, user_id: int) -> NotificationPreference | None:
        return (
            await self.db.execute(
                select(NotificationPreference)
                .where(NotificationPreference.mobile_user_id == user_id)
            )
        ).scalar_one_or_none()

    async def get_preference(
        self,
        *,
        actor: Actor,
        user_id: int,
    ) -> NotificationPreferenceRead:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view notification preferences.")

        if actor.actor_type == ActorType.MOBILE_USER:
            user_id = actor.id

        db_preference = await self._get_preference_by_user_id(user_id)
        if db_preference is None:
            return self.DEFAULT_PREFERENCES.model_copy(update={"mobile_user_id": user_id})

        return NotificationPreferenceRead.model_validate(db_preference)

    async def upsert(
        self,
        *,
        actor: Actor,
        user_id: int,
        preference_input: NotificationPreferenceUpdate,
    ) -> NotificationPreferenceRead:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to upsert notification preferences.")

        if actor.actor_type == ActorType.MOBILE_USER:
            user_id = actor.id

        db_preference = await self._get_preference_by_user_id(user_id)
        if db_preference is None:
            db_preference = NotificationPreference(mobile_user_id=user_id)
            self.db.add(db_preference)

        apply_partial_update(target=db_preference, input=preference_input)

        try:
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to upsert notification preference. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to upsert notification preference."
            ) from error

        await self.db.refresh(db_preference)
        return NotificationPreferenceRead.model_validate(db_preference)
