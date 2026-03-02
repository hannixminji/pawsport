import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.enums import ActorType
from ..core.exceptions.authorization_exceptions import ForbiddenError
from ..core.exceptions.db_exceptions import NonTransientDatabaseError, TransientDatabaseError
from ..core.schemas import Actor
from ..core.utils.update import apply_partial_update
from ..models.pet_qr_default import PetQRDefault
from ..schemas.pet_qr_default import PetQRDefaultRead, PetQRDefaultUpsert

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PetQRDefaultService:
    db: AsyncSession

    DEFAULT_PREFERENCES = PetQRDefaultRead(
        owner_id=None,
        show_owner_name=False,
        show_email=False,
        show_phone_number=False,
        show_address=False,
    )

    async def _get_default_by_owner_id(self, owner_id: int) -> PetQRDefault | None:
        return (
            await self.db.execute(
                select(PetQRDefault)
                .where(PetQRDefault.owner_id == owner_id)
            )
        ).scalar_one_or_none()

    async def get_default(
        self,
        *,
        actor: Actor,
        owner_id: int,
    ) -> PetQRDefaultRead:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view QR default preferences.")

        if actor.actor_type == ActorType.MOBILE_USER:
            owner_id = actor.id

        db_default = await self._get_default_by_owner_id(owner_id)
        if db_default is None:
            return self.DEFAULT_PREFERENCES.model_copy(update={"owner_id": owner_id})

        return PetQRDefaultRead.model_validate(db_default)

    async def upsert(
        self,
        *,
        actor: Actor,
        owner_id: int,
        default_input: PetQRDefaultUpsert,
    ) -> PetQRDefaultRead:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to upsert QR default preferences.")

        if actor.actor_type == ActorType.MOBILE_USER:
            owner_id = actor.id

        db_default = await self._get_default_by_owner_id(owner_id)
        if db_default is None:
            db_default = PetQRDefault(owner_id=owner_id)
            self.db.add(db_default)

        apply_partial_update(target=db_default, input=default_input)

        try:
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to upsert QR default preference. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to upsert QR default preference."
            ) from error

        await self.db.refresh(db_default)
        return PetQRDefaultRead.model_validate(db_default)
