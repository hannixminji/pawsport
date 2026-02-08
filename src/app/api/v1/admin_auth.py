from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated, Any, Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.db.database import async_get_db
from ...core.utils import admin_session_store
from ...core.utils.admin_sessions import (
    SessionEvent,
    SessionInfo,
    SessionManager,
    clear_admin_cookies,
    create_session_manager,
    set_admin_cookies,
)
from ...models.user import User

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])

ph = PasswordHasher()

LOGIN_WINDOW_SECONDS: Final[int] = 60
LOGIN_MAX_ATTEMPTS_PER_IP_USERNAME: Final[int] = 10
LOGIN_MAX_ATTEMPTS_PER_IP: Final[int] = 30

ADMIN_SLIDING_TTL_SECONDS: Final[int] = 60 * 30
ADMIN_ABSOLUTE_TTL_SECONDS: Final[int] = 60 * 60 * 12
ADMIN_MAX_SESSIONS_PER_USER: Final[int] = 3


class AdminLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=256)


class AdminMeOut(BaseModel):
    user_id: int
    username: str
    role: str | None = None


@dataclass(frozen=True)
class AdminUserRecord:
    id: int
    username: str
    password_hash: str
    role: str | None
    is_active: bool


async def get_redis() -> Redis:
    client = admin_session_store.client
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin session store is not initialized",
        )
    return client


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def enforce_login_rate_limit(redis: Redis, request: Request, username: str) -> int:
    ip = client_ip(request)
    key_user = f"admin:login:rl:{ip}:{username}"
    key_ip = f"admin:login:rl:{ip}"

    async with redis.pipeline(transaction=True) as p:
        p.incr(key_user)
        p.expire(key_user, LOGIN_WINDOW_SECONDS)
        p.incr(key_ip)
        p.expire(key_ip, LOGIN_WINDOW_SECONDS)
        user_attempts, _, ip_attempts, _ = await p.execute()

    if int(user_attempts) > LOGIN_MAX_ATTEMPTS_PER_IP_USERNAME or int(ip_attempts) > LOGIN_MAX_ATTEMPTS_PER_IP:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many login attempts")

    return int(user_attempts)


def is_production() -> bool:
    env = getattr(settings, "ENVIRONMENT", None)
    if isinstance(env, str):
        return env.lower() == "production"
    return False


async def get_session_manager(redis: Redis = Depends(get_redis)) -> SessionManager:
    return create_session_manager(
        redis_client=redis,
        sliding_time_to_live_seconds=ADMIN_SLIDING_TTL_SECONDS,
        absolute_time_to_live_seconds=ADMIN_ABSOLUTE_TTL_SECONDS,
        enable_session_binding=True,
        maximum_sessions_per_user=ADMIN_MAX_SESSIONS_PER_USER,
        cookie_secure=is_production(),
    )


async def require_admin_session(
    request: Request,
    sm: SessionManager = Depends(get_session_manager),
) -> SessionInfo:
    return await sm.require_session(request=request)


async def require_admin_csrf_session(
    request: Request,
    sm: SessionManager = Depends(get_session_manager),
) -> SessionInfo:
    return await sm.enforce_csrf(request=request)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return ph.verify(password_hash, password)
    except (VerificationError, InvalidHash):
        return False


async def get_admin_by_username(
    username: str,
    db: AsyncSession,
) -> AdminUserRecord | None:
    try:
        user = (
            await db.execute(
                select(User).where(
                    User.username == username,
                    ~User.is_deleted,
                )
            )
        ).scalar_one_or_none()
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )

    if user is None:
        return None

    password_hash = user.hashed_password
    if not isinstance(password_hash, str) or not password_hash:
        return None

    is_active = not bool(user.is_deleted)

    return AdminUserRecord(
        id=int(user.id),
        username=str(user.username),
        password_hash=password_hash,
        role="superuser" if bool(user.is_superuser) else None,
        is_active=is_active,
    )


@router.post("/login", response_model=AdminMeOut)
async def admin_login(
    request: Request,
    response: Response,
    payload: AdminLoginIn,
    redis: Annotated[Redis, Depends(get_redis)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> AdminMeOut:
    attempt_count = await enforce_login_rate_limit(redis, request, payload.username)

    admin = await get_admin_by_username(payload.username, db=db)
    if not admin or not admin.is_active or not verify_password(payload.password, admin.password_hash):
        sm.log_event(
            SessionEvent.LOGIN_FAILED,
            details={
                "reason": "invalid_credentials",
                "ip_address": client_ip(request),
                "attempt_count": attempt_count,
            },
            log_level=logging.INFO,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    session_id, csrf_token, _ = await sm.create_session(
        request=request,
        user_id=admin.id,
        metadata={"username": admin.username, "role": admin.role} if admin.role else {"username": admin.username},
    )

    signed = sm.sign_session_id(session_id)
    set_admin_cookies(
        response,
        signed_session=signed,
        csrf_token=csrf_token,
        cookie_secure=sm.cookie_secure,
    )

    sm.log_event(
        SessionEvent.LOGIN_SUCCESS,
        session_id=session_id,
        user_id=admin.id,
        details={"ip_address": client_ip(request)},
        log_level=logging.INFO,
    )

    return AdminMeOut(user_id=admin.id, username=admin.username, role=admin.role)


@router.post("/logout")
async def admin_logout(
    response: Response,
    session: SessionInfo = Depends(require_admin_csrf_session),
    sm: SessionManager = Depends(get_session_manager),
) -> dict[str, Any]:
    await sm.delete_session(session_id=session["session_id"], user_id=session["user_id"])
    clear_admin_cookies(response)
    sm.log_event(
        SessionEvent.LOGOUT,
        session_id=session["session_id"],
        user_id=session["user_id"],
        log_level=logging.INFO,
    )
    return {"ok": True}


@router.get("/me", response_model=AdminMeOut)
async def admin_me(session: SessionInfo = Depends(require_admin_session)) -> AdminMeOut:
    username = session.get("username")
    if not isinstance(username, str) or not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    role = session.get("role")
    role_str = role if isinstance(role, str) else None
    return AdminMeOut(user_id=session["user_id"], username=username, role=role_str)


@router.post("/logout_all")
async def admin_logout_all(
    response: Response,
    session: SessionInfo = Depends(require_admin_csrf_session),
    sm: SessionManager = Depends(get_session_manager),
) -> dict[str, Any]:
    await sm.delete_all_user_sessions(user_id=session["user_id"])
    clear_admin_cookies(response)
    sm.log_event(
        SessionEvent.LOGOUT,
        user_id=session["user_id"],
        log_level=logging.INFO,
    )
    return {"ok": True}
