import logging
from dataclasses import dataclass

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.enums import ActorType
from ..core.exceptions.authorization_exceptions import ForbiddenError
from ..core.exceptions.db_exceptions import NonTransientDatabaseError, TransientDatabaseError
from ..core.exceptions.domain_exceptions import NotFoundError
from ..core.schemas import Actor
from ..models.device_push_token import DevicePushToken
from ..schemas.device_push_token import DevicePushTokenUpsert

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class DevicePushTokenService:
    db: AsyncSession

    async def upsert(
        self,
        *,
        actor: Actor,
        user_id: int,
        token_input: DevicePushTokenUpsert,
    ) -> None:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to upsert push tokens.")

        if actor.actor_type == ActorType.MOBILE_USER:
            user_id = actor.id

        statement = (
            insert(DevicePushToken)
            .values(
                mobile_user_id=user_id,
                provider=token_input.provider,
                platform=token_input.platform,
                token=token_input.token,
            )
            .on_conflict_do_update(
                index_elements=[DevicePushToken.provider, DevicePushToken.token],
                set_={
                    "platform": token_input.platform,
                    "mobile_user_id": user_id,
                    "updated_at": func.now(),
                },
            )
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to save push token. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to save push token."
            ) from error

    async def hard_delete(
        self,
        *,
        actor: Actor,
        user_id: int,
        token: str,
    ) -> None:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to delete push tokens.")

        if actor.actor_type == ActorType.MOBILE_USER:
            user_id = actor.id

        try:
            result = (
                await self.db.execute(
                    delete(DevicePushToken)
                    .where(
                        DevicePushToken.token == token,
                        DevicePushToken.mobile_user_id == user_id,
                    )
                )
            )
            if result.rowcount == 0:
                raise NotFoundError("Push token not found.")

            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to delete push token. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete push token."
            ) from error
