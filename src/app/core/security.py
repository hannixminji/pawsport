import logging
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import Request
from fastapi.security import HTTPBearer, OAuth2PasswordBearer
from firebase_admin import auth
from firebase_admin.auth import CertificateFetchError, ExpiredIdTokenError, InvalidIdTokenError, RevokedIdTokenError
from firebase_admin.exceptions import FirebaseError
from jose import JWTError, jwt
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db.crud_token_blacklist import crud_token_blacklist
from .schemas import TokenBlacklistCreate, TokenData
from .utils.rbac_bitmap import PermissionIndex, roleset_has_permission

LOGGER = logging.getLogger(__name__)

SECRET_KEY: SecretStr = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/admin")
security = HTTPBearer()

argon2_settings = settings.password_hasher


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


def get_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else None


async def verify_password(plain_password: str, hashed_password: str) -> tuple[bool, str | None]:
    try:
        valid = argon2_settings.verify(hashed_password, plain_password)

        new_hash = None
        if argon2_settings.check_needs_rehash(hashed_password):
            new_hash = argon2_settings.hash(plain_password)

        return valid, new_hash

    except (VerifyMismatchError, VerificationError):
        return False, None


def get_password_hash(password: str) -> str:
    return argon2_settings.hash(password)


async def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC).replace(tzinfo=None) + expires_delta
    else:
        expire = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "token_type": TokenType.ACCESS})
    encoded_jwt: str = jwt.encode(to_encode, SECRET_KEY.get_secret_value(), algorithm=ALGORITHM)
    return encoded_jwt


async def create_refresh_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC).replace(tzinfo=None) + expires_delta
    else:
        expire = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "token_type": TokenType.REFRESH})
    encoded_jwt: str = jwt.encode(to_encode, SECRET_KEY.get_secret_value(), algorithm=ALGORITHM)
    return encoded_jwt


async def verify_token(token: str, expected_token_type: TokenType, db: AsyncSession) -> TokenData | None:
    """Verify a JWT token and return TokenData if valid.

    Parameters
    ----------
    token: str
        The JWT token to be verified.
    expected_token_type: TokenType
        The expected type of token (access or refresh)
    db: AsyncSession
        Database session for performing database operations.

    Returns
    -------
    TokenData | None
        TokenData instance if the token is valid, None otherwise.
    """
    is_blacklisted = await crud_token_blacklist.exists(db, token=token)
    if is_blacklisted:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY.get_secret_value(), algorithms=[ALGORITHM])
        username_or_email: str | None = payload.get("sub")
        token_type: str | None = payload.get("token_type")

        if username_or_email is None or token_type != expected_token_type:
            return None

        return TokenData(username_or_email=username_or_email)

    except JWTError:
        return None


async def blacklist_tokens(access_token: str, refresh_token: str, db: AsyncSession) -> None:
    """Blacklist both access and refresh tokens.

    Parameters
    ----------
    access_token: str
        The access token to blacklist
    refresh_token: str
        The refresh token to blacklist
    db: AsyncSession
        Database session for performing database operations.
    """
    for token in [access_token, refresh_token]:
        payload = jwt.decode(token, SECRET_KEY.get_secret_value(), algorithms=[ALGORITHM])
        exp_timestamp = payload.get("exp")
        if exp_timestamp is not None:
            expires_at = datetime.fromtimestamp(exp_timestamp)
            await crud_token_blacklist.create(db, object=TokenBlacklistCreate(token=token, expires_at=expires_at))


async def blacklist_token(token: str, db: AsyncSession) -> None:
    payload = jwt.decode(token, SECRET_KEY.get_secret_value(), algorithms=[ALGORITHM])
    exp_timestamp = payload.get("exp")
    if exp_timestamp is not None:
        expires_at = datetime.fromtimestamp(exp_timestamp)
        await crud_token_blacklist.create(db, object=TokenBlacklistCreate(token=token, expires_at=expires_at))


def verify_firebase_token(id_token: str) -> dict[str, Any]:
    try:
        return auth.verify_id_token(id_token)

    except ExpiredIdTokenError:
        raise ValueError("Firebase ID token has expired.")
    except RevokedIdTokenError:
        raise ValueError("Firebase ID token has been revoked.")
    except InvalidIdTokenError:
        raise ValueError("Invalid Firebase ID token.")
    except CertificateFetchError:
        raise ValueError("Error fetching Firebase public keys.")
    except FirebaseError as firebase_error:
        raise ValueError(f"Firebase error: {firebase_error}")


async def has_permission(
    *,
    db: AsyncSession,
    redis: Redis,
    permission_index: PermissionIndex,
    permission_key: str,
    role_ids: set[int] | None,
) -> bool:
    if not permission_key or not role_ids:
        return False

    try:
        validated_role_ids = {int(role_id) for role_id in role_ids if role_id is not None}
    except (TypeError, ValueError):
        return False

    if not validated_role_ids:
        return False

    if permission_key not in permission_index.by_key:
        return False

    try:
        is_allowed = await roleset_has_permission(
            db=db,
            redis=redis,
            perm_index=permission_index,
            role_ids=validated_role_ids,
            permission_key=permission_key,
        )
        return bool(is_allowed)

    except (TimeoutError, Exception):
        return False
