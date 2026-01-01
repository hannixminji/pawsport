from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..core.config import settings
from ..core.db.database import async_get_db
from ..core.exceptions.http_exceptions import ForbiddenException, RateLimitException, UnauthorizedException
from ..core.logger import logging
from ..core.security import TokenType, oauth2_scheme, security, verify_firebase_token, verify_token
from ..core.utils.rate_limit import rate_limiter
from ..crud.crud_rate_limit import crud_rate_limits
from ..crud.crud_tier import crud_tiers
from ..crud.crud_users import crud_users
from ..models.user_linked_account import UserLinkedAccount
from ..schemas.rate_limit import RateLimitRead, sanitize_path
from ..schemas.tier import TierRead
from ..schemas.user import UserRead

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = settings.DEFAULT_RATE_LIMIT_LIMIT
DEFAULT_PERIOD = settings.DEFAULT_RATE_LIMIT_PERIOD


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], db: Annotated[AsyncSession, Depends(async_get_db)]
) -> dict[str, Any]:
    token_data = await verify_token(token, TokenType.ACCESS, db)
    if token_data is None:
        raise UnauthorizedException("User not authenticated.")

    if "@" in token_data.username_or_email:
        user = await crud_users.get(db=db, email=token_data.username_or_email, is_deleted=False)
    else:
        user = await crud_users.get(db=db, username=token_data.username_or_email, is_deleted=False)

    if user:
        return user

    raise UnauthorizedException("User not authenticated.")


async def get_authenticated_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(async_get_db)]
) -> UserRead:
    token = credentials.credentials

    try:
        token_data = verify_firebase_token(token)
    except ValueError as error:
        raise UnauthorizedException(str(error))

    sign_in_provider = token_data.get("firebase", {}).get("sign_in_provider")

    identities = token_data.get("firebase", {}).get("identities", {})
    provider_ids = identities.get(sign_in_provider)
    provider_user_id = provider_ids[0]

    linked_account = (
        await db.execute(
            select(UserLinkedAccount)
            .options(selectinload(UserLinkedAccount.user))
            .where(
                UserLinkedAccount.provider == sign_in_provider,
                UserLinkedAccount.provider_user_id == provider_user_id,
                ~UserLinkedAccount.is_deleted
            )
        )
    ).scalar_one_or_none()

    if linked_account and linked_account.user and not linked_account.user.is_deleted:
        return UserRead.model_validate(linked_account.user)

    raise UnauthorizedException("User not authenticated.")


async def get_optional_user(request: Request, db: AsyncSession = Depends(async_get_db)) -> dict | None:
    token = request.headers.get("Authorization")
    if not token:
        return None

    try:
        token_type, _, token_value = token.partition(" ")
        if token_type.lower() != "bearer" or not token_value:
            return None

        token_data = await verify_token(token_value, TokenType.ACCESS, db)
        if token_data is None:
            return None

        return await get_current_user(token_value, db=db)

    except HTTPException as http_exc:
        if http_exc.status_code != 401:
            logger.error(f"Unexpected HTTPException in get_optional_user: {http_exc.detail}")
        return None

    except Exception as exc:
        logger.error(f"Unexpected error in get_optional_user: {exc}")
        return None


async def get_current_superuser(current_user: Annotated[dict, Depends(get_current_user)]) -> dict:
    if not current_user["is_superuser"]:
        raise ForbiddenException("You do not have enough privileges.")

    return current_user


async def get_authenticated_superuser(current_user: Annotated[UserRead, Depends(get_authenticated_user)]) -> UserRead:
    if not current_user.is_superuser:
        raise ForbiddenException("You do not have enough privileges.")

    return current_user


async def rate_limiter_dependency(
    request: Request, db: Annotated[AsyncSession, Depends(async_get_db)], user: dict | None = Depends(get_optional_user)
) -> None:
    if hasattr(request.app.state, "initialization_complete"):
        await request.app.state.initialization_complete.wait()

    path = sanitize_path(request.url.path)
    if user:
        user_id = user["id"]
        tier = await crud_tiers.get(db, id=user["tier_id"], schema_to_select=TierRead)
        if tier:
            rate_limit = await crud_rate_limits.get(
                db=db, tier_id=tier["id"], path=path, schema_to_select=RateLimitRead
            )
            if rate_limit:
                limit, period = rate_limit["limit"], rate_limit["period"]
            else:
                logger.warning(
                    f"User {user_id} with tier '{tier['name']}' has no specific rate limit for path '{path}'. \
                        Applying default rate limit."
                )
                limit, period = DEFAULT_LIMIT, DEFAULT_PERIOD
        else:
            logger.warning(f"User {user_id} has no assigned tier. Applying default rate limit.")
            limit, period = DEFAULT_LIMIT, DEFAULT_PERIOD
    else:
        user_id = request.client.host if request.client else "unknown"
        limit, period = DEFAULT_LIMIT, DEFAULT_PERIOD

    is_limited = await rate_limiter.is_rate_limited(db=db, user_id=user_id, path=path, limit=limit, period=period)
    if is_limited:
        raise RateLimitException("Rate limit exceeded.")
