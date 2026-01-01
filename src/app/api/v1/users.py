import asyncio
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastcrud import PaginatedListResponse, compute_offset, paginated_response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...api.dependencies import get_authenticated_superuser, get_authenticated_user
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import (
    DuplicateValueException,
    ForbiddenException,
    NotFoundException,
)
from ...core.utils.qdrant_cloud import delete_embedding
from ...models.pet import Pet
from ...models.user import User
from ...schemas.user import UserRead, UserUpdate

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["users"])


@router.get("/users", response_model=PaginatedListResponse[UserRead])
async def read_users(
    request: Request,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    page: int = 1,
    items_per_page: int = 10,
) -> dict[str, Any]:
    users = (
        await db.execute(
            select(User)
            .where(~User.is_deleted)
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(~User.is_deleted)
        )
    ).scalar_one()

    users_data = {
        "data": [UserRead.from_orm(user) for user in users],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(crud_data=users_data, page=page, items_per_page=items_per_page)
    return response


@router.get("/user/me/", response_model=UserRead)
async def read_users_me(
    request: Request,
    current_user: Annotated[UserRead, Depends(get_authenticated_user)]
) -> UserRead:
    return current_user


@router.get("/user/{username}", response_model=UserRead)
async def read_user(
    request: Request,
    username: str,
    db: Annotated[AsyncSession, Depends(async_get_db)]
) -> UserRead:
    db_user = (
        await db.execute(
            select(User)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if db_user is None:
        raise NotFoundException("User not found")

    return UserRead.model_validate(db_user)


@router.patch("/user/{username}")
async def patch_user(
    request: Request,
    values: UserUpdate,
    username: str,
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    db_user = (
        await db.execute(
            select(User)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user:
        raise NotFoundException("User not found")

    if current_user.id != db_user.id:
        raise ForbiddenException()

    for field, value in values.model_dump(exclude_unset=True).items():
        setattr(db_user, field, value)

    try:
        await db.commit()
        await db.refresh(db_user)

    except IntegrityError as integrity_error:
        await db.rollback()

        detail = str(integrity_error.orig)
        if "uq_user_email_not_deleted" in detail:
            field_name = "email"
        elif "uq_user_username_not_deleted" in detail:
            field_name = "username"
        elif "uq_user_phone_not_deleted" in detail:
            field_name = "phone number"
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred while updating your account. Please try again later."
            )

        raise DuplicateValueException(f"{field_name} already exists")

    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating your account. Please try again later."
        )

    return {"message": "User updated"}


@router.delete("/user/{username}")
async def erase_user(
    request: Request,
    username: str,
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    db_user = (
        await db.execute(
            select(User)
            .options(
                selectinload(User.linked_accounts),
                selectinload(User.pets).selectinload(Pet.profile_images)
            )
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user:
        raise NotFoundException("User not found.")

    if current_user.id != db_user.id:
        raise ForbiddenException()

    now = datetime.now(UTC)
    db_user.is_deleted = True
    db_user.deleted_at = now

    for linked_account in db_user.linked_accounts:
        linked_account.is_deleted = True
        linked_account.deleted_at = now

    all_profile_image_ids: list[int] = []

    for pet in db_user.pets:
        pet.is_deleted = True
        pet.deleted_at = now

        for profile_image in pet.profile_images:
            profile_image.is_deleted = True
            profile_image.deleted_at = now
            all_profile_image_ids.append(profile_image.id)

    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting your account. Please try again later.",
        )

    if all_profile_image_ids:
        try:
            await asyncio.to_thread(delete_embedding, "pet_profile_images", all_profile_image_ids)
        except Exception as error:
            LOGGER.warning(
                f"Failed to delete embeddings for pet_profile_images {all_profile_image_ids}: {error}"
            )

    return {"message": "User deleted"}


@router.delete("/db_user/{username}", dependencies=[Depends(get_authenticated_superuser)])
async def erase_db_user(
    request: Request,
    username: str,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    db_user = (
        await db.execute(
            select(User)
            .options(
                selectinload(User.pets).selectinload(Pet.profile_images)
            )
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user:
        raise NotFoundException("User not found.")

    all_profile_image_ids: list[int] = []
    for pet in db_user.pets:
        for profile_image in pet.profile_images:
            all_profile_image_ids.append(profile_image.id)

    try:
        await db.delete(db_user)
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the user. Please try again later."
        )

    if all_profile_image_ids:
        try:
            await asyncio.to_thread(delete_embedding, "pet_profile_images", all_profile_image_ids)
        except Exception as error:
            LOGGER.warning(
                f"Failed to delete embeddings for pet_profile_images {all_profile_image_ids}: {error}"
            )

    return {"message": "User deleted from the database"}
