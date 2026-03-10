import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.enums import UserTokenType
from ..core.exceptions.db_exceptions import NonTransientDatabaseError, TransientDatabaseError
from ..core.exceptions.domain_exceptions import InvalidInputError
from ..models.mobile_user_token import MobileUserToken

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class MobileUserTokenService:
    db: AsyncSession

    @staticmethod
    def _hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode(), usedforsecurity=True).hexdigest()

    @staticmethod
    def _get_expire_minutes(token_type: UserTokenType) -> int:
        return {
            UserTokenType.EMAIL_VERIFICATION: settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES,
            UserTokenType.EMAIL_CHANGE_OTP: settings.EMAIL_CHANGE_OTP_EXPIRE_MINUTES,
            UserTokenType.EMAIL_CHANGE: settings.EMAIL_CHANGE_TOKEN_EXPIRE_MINUTES,
            UserTokenType.PASSWORD_RESET: settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES,
        }[token_type]

    async def create_token(
        self,
        *,
        mobile_user_id: int,
        token_type: UserTokenType,
        payload: dict | None = None,
        raw_token: str | None = None,
    ) -> str:
        if raw_token is None:
            raw_token = secrets.token_urlsafe(32)
        token_hash = self._hash_token(raw_token)
        expires_at = datetime.now(UTC) + timedelta(minutes=self._get_expire_minutes(token_type))

        token_model = MobileUserToken(
            mobile_user_id=mobile_user_id,
            type=token_type,
            token_hash=token_hash,
            payload_json=payload,
            expires_at=expires_at,
        )

        self.db.add(token_model)

        try:
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to create token. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to create token."
            ) from error

        return raw_token

    async def verify_token(
        self,
        *,
        raw_token: str,
        token_type: UserTokenType,
    ) -> MobileUserToken:
        token_hash = self._hash_token(raw_token)

        db_token = (
            await self.db.execute(
                select(MobileUserToken)
                .where(
                    MobileUserToken.token_hash == token_hash,
                    MobileUserToken.type == token_type,
                    MobileUserToken.used_at.is_(None),
                    MobileUserToken.expires_at > datetime.now(UTC),
                )
            )
        ).scalar_one_or_none()

        if db_token is None:
            raise InvalidInputError("Invalid or expired token.")

        return db_token

    async def consume_token(
        self,
        *,
        token_id: int,
    ) -> None:
        statement = (
            update(MobileUserToken)
            .where(MobileUserToken.id == token_id)
            .values(used_at=datetime.now(UTC))
        )

        try:
            await self.db.execute(statement)

        except OperationalError as error:
            raise TransientDatabaseError(
                "Failed to consume token. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            raise NonTransientDatabaseError(
                "Failed to consume token."
            ) from error
