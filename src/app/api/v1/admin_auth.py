# api/admin_auth_routes.py
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

from ..core.config import settings
from ..core.utils.admin_session_store import async_get_admin_redis
from ..core.utils.admin_sessions import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    create_session,
    delete_session,
    enforce_admin_csrf,
    get_admin_session,
    require_admin_session,
    sign_session_id,
)

SLIDING_TTL_SECONDS = int(getattr(settings, "ADMIN_SESSION_TTL_SECONDS", 28800))
ABSOLUTE_TTL_SECONDS = int(getattr(settings, "ADMIN_SESSION_ABSOLUTE_TTL_SECONDS", SLIDING_TTL_SECONDS))

COOKIE_SECURE = bool(getattr(settings, "ADMIN_SESSION_COOKIE_SECURE", True))
COOKIE_SAMESITE = str(getattr(settings, "ADMIN_SESSION_COOKIE_SAMESITE", "lax"))
COOKIE_PATH = str(getattr(settings, "ADMIN_SESSION_COOKIE_PATH", "/admin"))


class AdminLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class AdminMeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int
    session: dict[str, Any]


async def verify_admin_credentials(username: str, password: str) -> int | None:
    raise NotImplementedError


def _set_cookies(response: Response, signed_session: str, csrf_token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=signed_session,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path=COOKIE_PATH,
        max_age=ABSOLUTE_TTL_SECONDS,
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path=COOKIE_PATH,
        max_age=ABSOLUTE_TTL_SECONDS,
    )


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path=COOKIE_PATH)
    response.delete_cookie(key=CSRF_COOKIE_NAME, path=COOKIE_PATH)


async def require_admin(
    request: Request,
    redis: Redis = Depends(async_get_admin_redis),
) -> dict[str, Any]:
    return await require_admin_session(
        request=request,
        redis=redis,
        sliding_ttl_seconds=SLIDING_TTL_SECONDS,
        absolute_ttl_seconds=ABSOLUTE_TTL_SECONDS,
    )


async def csrf_protect(
    request: Request,
    redis: Redis = Depends(async_get_admin_redis),
) -> None:
    await enforce_admin_csrf(
        request=request,
        redis=redis,
        sliding_ttl_seconds=SLIDING_TTL_SECONDS,
        absolute_ttl_seconds=ABSOLUTE_TTL_SECONDS,
    )


admin_router = APIRouter(prefix="/admin", tags=["admin"])


@admin_router.post("/login")
async def admin_login(
    payload: AdminLoginIn,
    response: Response,
    redis: Redis = Depends(async_get_admin_redis),
) -> dict[str, Any]:
    user_id = await verify_admin_credentials(payload.username, payload.password)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    session_id, csrf_token = await create_session(
        redis=redis,
        user_id=user_id,
        sliding_ttl_seconds=SLIDING_TTL_SECONDS,
        absolute_ttl_seconds=ABSOLUTE_TTL_SECONDS,
        metadata={"username": payload.username},
    )

    _set_cookies(response, sign_session_id(session_id), csrf_token)
    return {"ok": True}


@admin_router.get("/me", response_model=AdminMeOut)
async def admin_me(session: dict[str, Any] = Depends(require_admin)) -> AdminMeOut:
    return AdminMeOut(user_id=int(session["user_id"]), session=session)


@admin_router.post("/logout")
async def admin_logout(
    request: Request,
    response: Response,
    redis: Redis = Depends(async_get_admin_redis),
    _: None = Depends(csrf_protect),
) -> dict[str, Any]:
    session = await get_admin_session(
        request=request,
        redis=redis,
        sliding_ttl_seconds=SLIDING_TTL_SECONDS,
        absolute_ttl_seconds=ABSOLUTE_TTL_SECONDS,
    )
    if session and "_session_id" in session:
        await delete_session(redis, session["_session_id"])

    _clear_cookies(response)
    return {"ok": True}
