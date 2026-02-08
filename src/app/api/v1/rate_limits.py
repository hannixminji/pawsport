import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastcrud import PaginatedListResponse, compute_offset, paginated_response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.dependencies import get_authenticated_superuser
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import (
    BadRequestException,
    DuplicateValueException,
    NotFoundException,
)
from ...models.rate_limit import RateLimit
from ...models.tier import Tier
from ...schemas.rate_limit import RateLimitCreate, RateLimitRead, RateLimitUpdate

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["rate_limits"])


def _default_rate_limit_name(path: str, limit: int, period: int) -> str:
    return f"{path}:{limit}:{period}"


@router.post(
    "/tier/{tier_name}/rate_limit",
    dependencies=[Depends(get_authenticated_superuser)],
    response_model=RateLimitRead,
    status_code=201,
)
async def write_rate_limit(
    request: Request,
    tier_name: str,
    rate_limit: RateLimitCreate,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> RateLimitRead:
    db_tier = (
        await db.execute(
            select(Tier).where(
                Tier.name == tier_name,
                ~Tier.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_tier:
        raise NotFoundException("Tier not found")

    name = rate_limit.name or _default_rate_limit_name(rate_limit.path, rate_limit.limit, rate_limit.period)

    existing_by_name = (
        await db.execute(
            select(RateLimit.id).where(
                RateLimit.name == name,
                ~RateLimit.is_deleted
            )
        )
    ).scalar_one_or_none()
    if existing_by_name:
        raise DuplicateValueException("Rate Limit Name not available")

    existing_by_path = (
        await db.execute(
            select(RateLimit.id).where(
                RateLimit.tier_id == db_tier.id,
                RateLimit.path == rate_limit.path,
                ~RateLimit.is_deleted,
            )
        )
    ).scalar_one_or_none()
    if existing_by_path:
        raise DuplicateValueException("Rate Limit for this path already exists for this tier")

    rate_limit_model = RateLimit(
        tier_id=db_tier.id,
        path=rate_limit.path,
        limit=rate_limit.limit,
        period=rate_limit.period,
        name=name,
    )
    db.add(rate_limit_model)

    try:
        await db.commit()

    except IntegrityError:
        await db.rollback()

        raise BadRequestException("Unable to create the rate limit. Please try again.")

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the rate limit. Please try again later.",
        )

    await db.refresh(rate_limit_model)
    return RateLimitRead.model_validate(rate_limit_model)


@router.get(
    "/tier/{tier_name}/rate_limits",
    response_model=PaginatedListResponse[RateLimitRead],
)
async def read_rate_limits(
    request: Request,
    tier_name: str,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    page: int = 1,
    items_per_page: int = 10,
) -> dict[str, Any]:
    db_tier = (
        await db.execute(
            select(Tier.id).where(
                Tier.name == tier_name,
                ~Tier.is_deleted,
            )
        )
    ).scalar_one_or_none()
    if not db_tier:
        raise NotFoundException("Tier not found")

    db_rate_limits = (
        await db.execute(
            select(RateLimit)
            .where(
                RateLimit.tier_id == db_tier,
                ~RateLimit.is_deleted,
            )
            .order_by(RateLimit.created_at.desc())
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(RateLimit)
            .where(
                RateLimit.tier_id == db_tier,
                ~RateLimit.is_deleted,
            )
        )
    ).scalar_one()

    rate_limits_data = {
        "data": [RateLimitRead.model_validate(item) for item in db_rate_limits],
        "total_count": total_count,
    }

    response: dict[str, Any] = paginated_response(
        crud_data=rate_limits_data,
        page=page,
        items_per_page=items_per_page,
    )
    return response


@router.get(
    "/tier/{tier_name}/rate_limit/{id}",
    response_model=RateLimitRead,
)
async def read_rate_limit(
    request: Request,
    tier_name: str,
    id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> RateLimitRead:
    db_tier_id = (
        await db.execute(
            select(Tier.id).where(
                Tier.name == tier_name,
                ~Tier.is_deleted,
            )
        )
    ).scalar_one_or_none()
    if not db_tier_id:
        raise NotFoundException("Tier not found")

    db_rate_limit = (
        await db.execute(
            select(RateLimit).where(
                RateLimit.id == id,
                RateLimit.tier_id == db_tier_id,
                ~RateLimit.is_deleted,
            )
        )
    ).scalar_one_or_none()
    if not db_rate_limit:
        raise NotFoundException("Rate Limit not found")

    return RateLimitRead.model_validate(db_rate_limit)


@router.patch(
    "/tier/{tier_name}/rate_limit/{id}",
    dependencies=[Depends(get_authenticated_superuser)],
)
async def patch_rate_limit(
    request: Request,
    tier_name: str,
    id: int,
    values: RateLimitUpdate,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    db_tier_id = (
        await db.execute(
            select(Tier.id).where(
                Tier.name == tier_name,
                ~Tier.is_deleted,
            )
        )
    ).scalar_one_or_none()
    if not db_tier_id:
        raise NotFoundException("Tier not found")

    db_rate_limit = (
        await db.execute(
            select(RateLimit).where(
                RateLimit.id == id,
                RateLimit.tier_id == db_tier_id,
                ~RateLimit.is_deleted,
            )
        )
    ).scalar_one_or_none()
    if not db_rate_limit:
        raise NotFoundException("Rate Limit not found")

    update_data = values.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(db_rate_limit, field, value)

    # If name not explicitly set, keep current name unless you want auto-regenerate
    if "name" not in update_data and any(k in update_data for k in {"path", "limit", "period"}):
        db_rate_limit.name = _default_rate_limit_name(
            db_rate_limit.path,
            db_rate_limit.limit,
            db_rate_limit.period,
        )

    db_rate_limit.updated_at = datetime.now(UTC)

    try:
        await db.commit()

    except IntegrityError:
        await db.rollback()
        raise BadRequestException("Unable to update the rate limit. Please try again.")

    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the rate limit. Please try again later.",
        )

    return {"message": "Rate Limit updated"}


@router.delete(
    "/tier/{tier_name}/rate_limit/{id}",
    dependencies=[Depends(get_authenticated_superuser)],
)
async def erase_rate_limit(
    request: Request,
    tier_name: str,
    id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    db_tier_id = (
        await db.execute(
            select(Tier.id).where(
                Tier.name == tier_name,
                ~Tier.is_deleted,
            )
        )
    ).scalar_one_or_none()
    if not db_tier_id:
        raise NotFoundException("Tier not found")

    db_rate_limit = (
        await db.execute(
            select(RateLimit).where(
                RateLimit.id == id,
                RateLimit.tier_id == db_tier_id,
                ~RateLimit.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_rate_limit:
        raise NotFoundException("Rate Limit not found")

    now = datetime.now(UTC)
    db_rate_limit.is_deleted = True
    db_rate_limit.deleted_at = now
    db.add(db_rate_limit)

    try:
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the rate limit. Please try again later.",
        )

    return {"message": "Rate Limit deleted"}
