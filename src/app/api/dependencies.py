import asyncio
import logging
from typing import Annotated

from fastapi import Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import any_, exists, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from ..core.config import settings
from ..core.db.database import async_get_db
from ..core.enums import ActorType, AdminAccountStatus
from ..core.exceptions.http_exceptions import (
    CustomException,
    ForbiddenException,
    RateLimitException,
    UnauthorizedException,
)
from ..core.schemas import Actor
from ..core.security import security, verify_firebase_token
from ..core.utils import cache
from ..core.utils.admin_sessions import (
    SessionInfo,
    SessionManager,
    clear_admin_cookies,
    create_session_manager,
)
from ..core.utils.rate_limit import rate_limiter
from ..core.utils.rbac_bitmap import (
    PermissionIndex,
    get_schema_version,
    load_permission_index,
    roleset_has_permission,
)
from ..models._rbac_table import admin_role_permission
from ..models.admin_permission import AdminPermission
from ..models.admin_role import AdminRole
from ..models.admin_user import AdminUser
from ..models.mobile_user import MobileUser
from ..models.rate_limit import RateLimit
from ..models.tier import Tier
from ..models.user_linked_account import UserLinkedAccount
from ..schemas.admin_user import AdminActor
from ..schemas.mobile_user import MobileActor
from ..schemas.rate_limit import sanitize_path

LOGGER = logging.getLogger(__name__)

_perm_index_reload_lock = asyncio.Lock()


async def get_redis_safe(request: Request) -> Redis:
    from app.core.utils import admin_session_store as _store
    client = _store.client
    if client is None:
        raise CustomException(status_code=503, detail="Admin session store is not available")
    return client


def get_session_manager(
    redis: Annotated[Redis, Depends(get_redis_safe)],
) -> SessionManager:
    return create_session_manager(
        redis_client=redis,
        sliding_time_to_live_seconds=settings.ADMIN_SESSION_TTL_SECONDS,
        absolute_time_to_live_seconds=settings.ADMIN_SESSION_ABSOLUTE_TTL_SECONDS,
        enable_session_binding=True,
        maximum_sessions_per_user=settings.ADMIN_SESSION_MAXIMUM_SESSIONS_PER_USER,
        cookie_secure=settings.ADMIN_SESSION_COOKIE_SECURE,
    )


async def require_admin_session(
    request: Request,
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> SessionInfo:
    return await sm.require_session(request=request)


async def require_admin_csrf_session(
    request: Request,
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> SessionInfo:
    return await sm.enforce_csrf(request=request)


async def get_redis_cache_client() -> Redis:
    return cache.client


async def get_permission_index(
    request: Request,
    redis: Annotated[Redis, Depends(get_redis_cache_client)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> PermissionIndex:
    app = request.app
    current_version = await get_schema_version(redis)

    if (
        not hasattr(app.state, "perm_index")
        or not hasattr(app.state, "perm_schema_version")
        or app.state.perm_schema_version != current_version
    ):
        async with _perm_index_reload_lock:
            if (
                not hasattr(app.state, "perm_index")
                or not hasattr(app.state, "perm_schema_version")
                or app.state.perm_schema_version != current_version
            ):
                LOGGER.info(
                    "Reloading permission index (schema version: %d -> %d)",
                    getattr(app.state, "perm_schema_version", -1),
                    current_version,
                )
                app.state.perm_index = await load_permission_index(db)
                app.state.perm_schema_version = current_version

    return app.state.perm_index


async def check_permission_direct_db(
    db: AsyncSession,
    role_ids: set[int],
    permission_key: str,
) -> bool:
    statement = select(
        exists().where(
            admin_role_permission.c.admin_role_id == any_(list(role_ids)),
            admin_role_permission.c.admin_permission_id == AdminPermission.id,
            AdminPermission.key == permission_key,
        )
    )
    result = await db.execute(statement)
    return result.scalar()


def require_permission(permission_key: str):
    async def dependency(
        admin_user: Annotated[AdminActor, Depends(get_current_admin_user)],
        redis: Annotated[Redis, Depends(get_redis_cache_client)],
        db: Annotated[AsyncSession, Depends(async_get_db)],
        perm_index: Annotated[PermissionIndex, Depends(get_permission_index)],
    ) -> None:
        if admin_user.is_superuser:
            return

        role_ids = set(admin_user.roles)
        if not role_ids:
            raise ForbiddenException("You do not have any roles assigned.")

        try:
            has_perm = await roleset_has_permission(
                db=db,
                redis=redis,
                perm_index=perm_index,
                role_ids=role_ids,
                permission_key=permission_key,
            )
        except (TimeoutError, RedisError, ConnectionError) as e:
            LOGGER.warning(
                (
                    "Bitmap permission check failed (error: %s). "
                    "Falling back to direct DB query for user_id=%d, permission=%s"
                ),
                type(e).__name__,
                admin_user.id,
                permission_key,
            )
            try:
                has_perm = await check_permission_direct_db(db, role_ids, permission_key)
            except Exception:
                LOGGER.exception(
                    "Direct DB permission check also failed for user_id=%d, permission=%s",
                    admin_user.id,
                    permission_key,
                )
                raise CustomException(status_code=503, detail="Unable to verify permissions at this time.")
        except Exception:
            LOGGER.exception(
                "Unexpected error during permission check for user_id=%d, permission=%s",
                admin_user.id,
                permission_key,
            )
            raise CustomException(status_code=503, detail="Permission verification failed due to an internal error.")

        if not has_perm:
            raise ForbiddenException("You do not have permission to perform this action.")

    return dependency


async def get_current_mobile_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> MobileActor:
    token = credentials.credentials

    try:
        token_data = verify_firebase_token(token)
    except ValueError as error:
        raise UnauthorizedException(str(error))

    sign_in_provider = token_data.get("firebase", {}).get("sign_in_provider")
    identities = token_data.get("firebase", {}).get("identities", {})
    provider_ids = identities.get(sign_in_provider)
    if not provider_ids:
        raise UnauthorizedException("Invalid token: missing provider user ID")
    provider_user_id = provider_ids[0]

    try:
        mobile_user = (
            await db.execute(
                select(MobileUser)
                .options(load_only(MobileUser.id, MobileUser.tier_id, MobileUser.is_deleted))
                .join(UserLinkedAccount, UserLinkedAccount.mobile_user_id == MobileUser.id)
                .where(
                    UserLinkedAccount.provider == sign_in_provider,
                    UserLinkedAccount.provider_user_id == provider_user_id,
                    UserLinkedAccount.is_deleted.is_(False),
                    MobileUser.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
    except SQLAlchemyError:
        LOGGER.exception("Database error while fetching mobile user for provider_user_id=%s", provider_user_id)
        raise CustomException(status_code=500, detail="An unexpected error occurred. Please try again later.")

    if mobile_user:
        return MobileActor(
            id=mobile_user.id,
            tier_id=mobile_user.tier_id,
            actor_type=ActorType.MOBILE,
        )

    raise UnauthorizedException("User not authenticated.")


async def get_current_admin_user(
    response: Response,
    session: Annotated[SessionInfo, Depends(require_admin_session)],
    session_manager: Annotated[SessionManager, Depends(get_session_manager)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> AdminActor:
    session_id = session["session_id"]
    user_id = session["user_id"]

    async def _invalidate_session() -> None:
        await session_manager.delete_session(session_id=session_id, user_id=user_id)
        clear_admin_cookies(response)

    try:
        admin_user = (
            await db.execute(
                select(AdminUser)
                .options(
                    load_only(AdminUser.id, AdminUser.account_status, AdminUser.is_superuser),
                    selectinload(AdminUser.roles).load_only(AdminRole.id),
                )
                .where(
                    AdminUser.id == user_id,
                    AdminUser.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
    except SQLAlchemyError:
        LOGGER.exception("Database error while fetching admin user for user_id=%d", user_id)
        raise CustomException(status_code=500, detail="An unexpected error occurred. Please try again later.")

    if admin_user is None:
        await _invalidate_session()
        raise UnauthorizedException("Your session is no longer valid. Please log in again.")

    if admin_user.account_status == AdminAccountStatus.SUSPENDED:
        await _invalidate_session()
        raise ForbiddenException("Your account has been suspended. Please contact support for assistance.")

    if admin_user.account_status == AdminAccountStatus.INACTIVE:
        await _invalidate_session()
        raise ForbiddenException("Your account is inactive. Please contact an administrator to reactivate it.")

    role_ids = [role.id for role in admin_user.roles]

    return AdminActor(
        id=admin_user.id,
        actor_type=ActorType.ADMIN_USER,
        is_superuser=admin_user.is_superuser,
        role_ids=role_ids,
    )


async def get_current_admin_superuser(
    admin_user: Annotated[AdminActor, Depends(get_current_admin_user)],
) -> AdminActor:
    if not admin_user.is_superuser:
        raise ForbiddenException("You do not have permission to perform this action. Superuser access is required.")
    return admin_user


async def rate_limiter_dependency(
    request: Request,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    user: Annotated[MobileActor, Depends(get_current_mobile_user)],
) -> Actor:
    if hasattr(request.app.state, "initialization_complete"):
        await request.app.state.initialization_complete.wait()

    path = sanitize_path(request.url.path)
    user_id = str(user.id)

    rate_limit = (
        await db.execute(
            select(RateLimit)
            .join(Tier, Tier.id == RateLimit.tier_id)
            .where(
                Tier.id == user.tier_id,
                RateLimit.path == path,
            )
        )
    ).scalar_one_or_none()

    if rate_limit:
        limit, period = rate_limit.limit, rate_limit.period
    else:
        LOGGER.warning(
            "User %s with tier_id=%s has no specific rate limit for path '%s'. Applying default rate limit.",
            user_id,
            user.tier_id,
            path,
        )
        limit, period = settings.DEFAULT_RATE_LIMIT_LIMIT, settings.DEFAULT_RATE_LIMIT_PERIOD

    is_limited = await rate_limiter.is_rate_limited(
        db=db,
        user_id=user_id,
        path=path,
        limit=limit,
        period=period,
    )

    if is_limited:
        raise RateLimitException("Rate limit exceeded.")

    return user.to_actor(request)


async def get_current_admin_actor(
    request: Request,
    admin_user: Annotated[AdminActor, Depends(get_current_admin_user)],
) -> Actor:
    return admin_user.to_actor(request)


async def get_current_superuser_actor(
    request: Request,
    admin_user: Annotated[AdminActor, Depends(get_current_admin_superuser)],
) -> Actor:
    return admin_user.to_actor(request)


async def get_current_mobile_actor(
    request: Request,
    mobile_user: Annotated[MobileActor, Depends(get_current_mobile_user)],
) -> Actor:
    return mobile_user.to_actor(request)
