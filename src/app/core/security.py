import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi.security import HTTPBearer, OAuth2PasswordBearer
from firebase_admin import auth
from firebase_admin.auth import CertificateFetchError, ExpiredIdTokenError, InvalidIdTokenError, RevokedIdTokenError
from firebase_admin.exceptions import FirebaseError
from jose import JWTError, jwt
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.refresh_session import RefreshSession
from ..schemas.token import TokenData
from .config import settings
from .utils.rbac_bitmap import PermissionIndex, roleset_has_permission

LOGGER = logging.getLogger(__name__)

SECRET_KEY: str = settings.SECRET_KEY.get_secret_value()
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/admin")
security = HTTPBearer()

argon2_settings = settings.password_hasher


class TokenType(StrEnum):
    ACCESS = "access"


# ── helpers ──

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


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


# ── access token (stateless JWT) ──

async def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    to_encode = data.copy()
    now = datetime.now(UTC).replace(tzinfo=None)
    expire = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({
        "exp": expire,
        "iat": now,
        "token_type": TokenType.ACCESS,
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def verify_access_token(token: str) -> TokenData | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

    user_id: str | None = payload.get("sub")
    token_type: str | None = payload.get("token_type")

    if user_id is None or token_type != TokenType.ACCESS:
        return None

    return TokenData(user_id=int(user_id))


# ── refresh token (stateful opaque) ──

def generate_refresh_token() -> tuple[str, str]:
    """Return (opaque_token, token_hash)."""
    token = secrets.token_urlsafe(64)
    return token, _hash_token(token)


async def create_refresh_session(
    db: AsyncSession,
    user_id: int,
    token_hash: str,
    device_id: str | None = None,
    expires_delta: timedelta | None = None,
) -> None:
    expires_at = datetime.now(UTC) + (expires_delta or timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))
    db.add(RefreshSession(
        user_id=user_id,
        token_hash=token_hash,
        device_id=device_id,
        expires_at=expires_at,
    ))
    await db.flush()


async def verify_refresh_token(token: str, db: AsyncSession) -> TokenData | None:
    token_hash = _hash_token(token)
    now = datetime.now(UTC)
    session = (
        await db.execute(
            select(RefreshSession)
            .where(
                RefreshSession.token_hash == token_hash,
                RefreshSession.revoked_at.is_(None),
                RefreshSession.expires_at > now,
            )
        )
    ).scalar_one_or_none()
    if session is None:
        return None

    return TokenData(user_id=session.user_id)


async def revoke_refresh_session(token: str, db: AsyncSession) -> None:
    token_hash = _hash_token(token)
    await db.execute(
        update(RefreshSession)
        .where(
            RefreshSession.token_hash == token_hash,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )


async def revoke_all_user_sessions(user_id: int, db: AsyncSession) -> None:
    await db.execute(
        update(RefreshSession)
        .where(
            RefreshSession.user_id == user_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )


# ── rotation (atomic — replay-safe) ──

async def rotate_refresh_token(
    refresh_token: str,
    db: AsyncSession,
) -> tuple[str, str, int] | None:
    token_hash = _hash_token(refresh_token)
    now = datetime.now(UTC)

    result = await db.execute(
        update(RefreshSession)
        .where(
            RefreshSession.token_hash == token_hash,
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > now,
        )
        .values(revoked_at=now)
        .returning(RefreshSession.user_id)
    )

    row = result.first()
    if row is None:
        return None

    user_id = row.user_id

    new_access = await create_access_token(data={"sub": str(user_id)})
    new_opaque, new_hash = generate_refresh_token()
    await create_refresh_session(db, user_id, new_hash)

    return new_access, new_opaque, user_id


# ── firebase ──

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


def create_firebase_custom_token(user_id: int | str) -> str | None:
    """Mint a Firebase custom token for the given user ID.
    Used to bridge custom JWT auth with Firestore security rules.
    Returns None if Firebase is unavailable; caller should handle gracefully.
    """
    try:
        token_bytes = auth.create_custom_token(str(user_id))
        return token_bytes.decode("utf-8")
    except FirebaseError as firebase_error:
        LOGGER.error(f"Failed to create Firebase custom token for user {user_id}: {firebase_error}")
        return None


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
