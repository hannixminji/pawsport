import hashlib
import logging
from typing import Annotated, Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError
from fastapi import Depends, Request, Response
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter, csrf_exempt
from app.api.dependencies import (
    get_redis_safe,
    get_session_manager,
    require_admin_csrf_session,
    require_admin_session,
)
from app.core.config import settings
from app.core.db.database import async_get_db
from app.core.enums import AdminAccountStatus
from app.core.exceptions.http_exceptions import (
    CustomException,
    ForbiddenException,
    RateLimitException,
    UnauthorizedException,
)
from app.core.utils.admin_sessions import (
    SessionEvent,
    SessionInfo,
    SessionManager,
    clear_admin_cookies,
    set_admin_cookies,
)
from app.models.admin_user import AdminUser
from app.schemas.admin_user import AdminLoginResponse, AdminUserLogin, AdminUserRead

LOGGER = logging.getLogger(__name__)

router = CSRFProtectedRouter(prefix="/auth", tags=["Admin Auth"])

ph = PasswordHasher()
_DUMMY_HASH: str = ph.hash("__dummy_password_for_timing_safety__")


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _enforce_login_rate_limit(
    redis: Redis,
    request: Request,
    username: str,
) -> int:
    ip = _client_ip(request)
    username_hash = hashlib.sha256(username.encode()).hexdigest()[:16]
    key_user = f"admin:login:rl:{ip}:{username_hash}"
    key_ip = f"admin:login:rl:{ip}"

    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(key_user)
        pipe.expire(key_user, settings.LOGIN_WINDOW_SECONDS)
        pipe.incr(key_ip)
        pipe.expire(key_ip, settings.LOGIN_WINDOW_SECONDS)
        user_attempts, _, ip_attempts, _ = await pipe.execute()

    if (
        int(user_attempts) > settings.LOGIN_MAX_ATTEMPTS_PER_IP_USERNAME
        or int(ip_attempts) > settings.LOGIN_MAX_ATTEMPTS_PER_IP
    ):
        raise RateLimitException("Too many login attempts. Please try again later.")

    return int(user_attempts)


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return ph.verify(password_hash, password)
    except (VerificationError, InvalidHash):
        return False


def _needs_rehash(password_hash: str) -> bool:
    try:
        return ph.check_needs_rehash(password_hash)
    except Exception:
        return False


async def _get_admin_by_username(username: str, db: AsyncSession) -> AdminUser | None:
    try:
        return (
            await db.execute(
                select(AdminUser).where(
                    AdminUser.username == username,
                    AdminUser.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
    except SQLAlchemyError:
        LOGGER.exception("Database error fetching admin user %r", username)
        raise CustomException(status_code=500, detail="An unexpected error occurred.")


@router.post("/login", response_model=AdminLoginResponse)
@csrf_exempt
async def admin_login(
    request: Request,
    response: Response,
    payload: AdminUserLogin,
    redis: Annotated[Redis, Depends(get_redis_safe)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> AdminLoginResponse:
    attempt_count = await _enforce_login_rate_limit(redis, request, payload.username)

    user = await _get_admin_by_username(payload.username, db=db)

    if user is None or not isinstance(user.hashed_password, str) or not user.hashed_password:
        _verify_password(payload.password, _DUMMY_HASH)
        _log_failed_login(sm, request, payload.username, attempt_count)
        raise UnauthorizedException("Invalid credentials")

    if not _verify_password(payload.password, user.hashed_password):
        _log_failed_login(sm, request, payload.username, attempt_count)
        raise UnauthorizedException("Invalid credentials")

    if user.account_status == AdminAccountStatus.SUSPENDED:
        raise ForbiddenException("Your account has been suspended. Please contact support.")

    if user.account_status == AdminAccountStatus.INACTIVE:
        raise ForbiddenException("Your account is inactive.")

    if _needs_rehash(user.hashed_password):
        await _rehash_password(user.id, payload.password, db)

    session_id, csrf_token, _ = await sm.create_session(
        request=request,
        user_id=user.id,
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
        user_id=user.id,
        details={"ip_address": _client_ip(request)},
        log_level=logging.INFO,
    )

    return AdminLoginResponse.model_validate(user)


@router.post("/logout")
async def admin_logout(
    response: Response,
    session: Annotated[SessionInfo, Depends(require_admin_csrf_session)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
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


@router.get("/me", response_model=AdminUserRead)
async def admin_me(
    response: Response,
    session: Annotated[SessionInfo, Depends(require_admin_session)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> AdminUserRead:
    user_id = session["user_id"]
    try:
        user = (
            await db.execute(
                select(AdminUser).where(
                    AdminUser.id == user_id,
                    AdminUser.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
    except SQLAlchemyError:
        LOGGER.exception("Database error fetching admin user_id=%d in /me", user_id)
        raise CustomException(status_code=500, detail="An unexpected error occurred.")

    if user is None:
        await sm.delete_session(session_id=session["session_id"], user_id=user_id)
        clear_admin_cookies(response)
        raise UnauthorizedException("Not authenticated")

    if user.account_status in (AdminAccountStatus.SUSPENDED, AdminAccountStatus.INACTIVE):
        await sm.delete_session(session_id=session["session_id"], user_id=user_id)
        clear_admin_cookies(response)
        raise ForbiddenException("Your account is not active.")

    return AdminUserRead.model_validate(user)


@router.post("/logout_all")
async def admin_logout_all(
    response: Response,
    session: Annotated[SessionInfo, Depends(require_admin_csrf_session)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> dict[str, Any]:
    await sm.delete_all_user_sessions(user_id=session["user_id"])
    clear_admin_cookies(response)
    sm.log_event(
        SessionEvent.LOGOUT,
        user_id=session["user_id"],
        log_level=logging.INFO,
    )
    return {"ok": True}


def _log_failed_login(
    sm: SessionManager,
    request: Request,
    username: str,
    attempt_count: int,
) -> None:
    sm.log_event(
        SessionEvent.LOGIN_FAILED,
        details={
            "reason": "invalid_credentials",
            "ip_address": _client_ip(request),
            "attempt_count": attempt_count,
        },
        log_level=logging.WARNING,
    )


async def _rehash_password(user_id: int, plaintext: str, db: AsyncSession) -> None:
    try:
        new_hash = ph.hash(plaintext)
        user = (
            await db.execute(
                select(AdminUser)
                .where(
                    AdminUser.id == user_id,
                    AdminUser.is_deleted.is_(False),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if user is None:
            return
        user.hashed_password = new_hash
        await db.commit()
    except SQLAlchemyError:
        LOGGER.exception("Non-fatal: failed to rehash password for user_id=%d", user_id)
        await db.rollback()
