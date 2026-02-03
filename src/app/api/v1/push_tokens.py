import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.dependencies import get_authenticated_user
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import BadRequestException, NotFoundException
from ...models.push_token import PushToken as PushTokenModel
from ...schemas.push_token import PushTokenUpsert
from ...schemas.user import UserRead

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/push_tokens", tags=["push_tokens"])


@router.post("/push_tokens", status_code=status.HTTP_204_NO_CONTENT)
async def upsert_push_token(
    request: Request,
    values: PushTokenUpsert,
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> None:
    now = datetime.now(UTC)

    push_token_model = PushTokenModel(
        **values.model_dump(),
        user_id=current_user.id,
        last_seen_at=now
    )
    db.add(push_token_model)

    try:
        await db.commit()

    except IntegrityError:
        await db.rollback()

        try:
            await db.execute(
                update(PushTokenModel)
                .where(PushTokenModel.token == values.token)
                .values(
                    **values.model_dump(),
                    user_id=current_user.id,
                    last_seen_at=now,
                    updated_at=now
                )
            )
            await db.commit()

        except SQLAlchemyError:
            await db.rollback()

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred while saving the push token. Please try again later."
            )

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while saving the push token. Please try again later."
        )


@router.delete("/push_tokens/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def erase_push_token(
    request: Request,
    token: str,
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> None:
    if not token:
        raise BadRequestException("Token is required")

    db_push_token = (
        await db.execute(
            select(PushTokenModel)
            .where(
                PushTokenModel.token == token,
                PushTokenModel.user_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    if not db_push_token:
        raise NotFoundException("Push token not found")

    try:
        await db.delete(db_push_token)
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the push token. Please try again later."
        )
