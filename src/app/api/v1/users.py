from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Union

from argon2 import PasswordHasher
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastcrud import PaginatedListResponse, compute_offset, paginated_response
from geoalchemy2.shape import from_shape
from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely.geometry import Point
from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...api.dependencies import get_authenticated_superuser, get_authenticated_user
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import (
    BadRequestException,
    DuplicateValueException,
    ForbiddenException,
    NotFoundException,
)
from ...core.utils.qdrant_cloud import delete_embedding
from ...models.pet import Pet
from ...models.user import User
from ...schemas.user import UserCreate, UserRead, UserUpdate

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["users"])

ph = PasswordHasher()


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class UserSortBy(StrEnum):
    USERNAME = "username"
    EMAIL = "email"
    PHONE_NUMBER = "phone_number"
    CREATED_AT = "created_at"


class FilterOp(StrEnum):
    EQ = "eq"
    ILIKE = "ilike"
    GTE = "gte"
    LTE = "lte"
    IN = "in"


class UserFilterField(StrEnum):
    USERNAME = "username"
    EMAIL = "email"
    PHONE_NUMBER = "phone_number"
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    COUNTRY = "country"
    CITY = "city"
    STATE_PROVINCE_REGION = "state_province_region"
    CREATED_AT = "created_at"


class WhereRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["rule"]
    field: UserFilterField
    op: FilterOp
    value: Any


class WhereGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["group"]
    op: Literal["and", "or"]
    conditions: list[WhereNode] = Field(min_length=1, max_length=50)


class WhereNot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["not"]
    condition: WhereNode


WhereNode = Annotated[Union[WhereRule, WhereGroup, WhereNot], Field(discriminator="type")]


class UserSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1)
    items_per_page: int = Field(10, ge=1, le=100)

    sort_by: UserSortBy = UserSortBy.CREATED_AT
    sort_order: SortOrder = SortOrder.DESC

    where: WhereNode | None = None

    @model_validator(mode="after")
    def limit_complexity(self):
        def count_nodes(node: WhereNode, depth: int = 0) -> int:
            if depth > 10:
                raise ValueError("where is too deeply nested")

            if isinstance(node, WhereRule):
                return 1

            if isinstance(node, WhereNot):
                return 1 + count_nodes(node.condition, depth + 1)

            total = 1
            for child in node.conditions:
                total += count_nodes(child, depth + 1)
            return total

        if self.where is not None:
            total = count_nodes(self.where, 0)
            if total > 200:
                raise ValueError("where is too large")
        return self


def build_where(node: WhereNode, filter_columns: dict[UserFilterField, Any]):  # noqa: C901
    if isinstance(node, WhereRule):
        column = filter_columns[node.field]
        value = node.value

        ilike_fields = {
            UserFilterField.USERNAME,
            UserFilterField.EMAIL,
            UserFilterField.PHONE_NUMBER,
            UserFilterField.FIRST_NAME,
            UserFilterField.LAST_NAME,
            UserFilterField.COUNTRY,
            UserFilterField.CITY,
            UserFilterField.STATE_PROVINCE_REGION,
        }

        if node.field in ilike_fields:
            if node.op not in {FilterOp.EQ, FilterOp.ILIKE, FilterOp.IN}:
                raise BadRequestException("This field only supports eq, ilike, or in.")

        if node.field == UserFilterField.CREATED_AT:
            if node.op not in {FilterOp.EQ, FilterOp.GTE, FilterOp.LTE}:
                raise BadRequestException("created_at only supports eq, gte, or lte.")

        if node.op == FilterOp.EQ:
            return column == value

        if node.op == FilterOp.ILIKE:
            if not isinstance(value, str):
                raise BadRequestException("ILIKE value must be a string.")
            return column.ilike(f"%{value}%")

        if node.op == FilterOp.GTE:
            return column >= value

        if node.op == FilterOp.LTE:
            return column <= value

        if node.op == FilterOp.IN:
            if not isinstance(value, list) or not value:
                raise BadRequestException("IN value must be a non-empty list.")
            return column.in_(value)

        raise BadRequestException("Invalid filter operator.")

    if isinstance(node, WhereNot):
        return not_(build_where(node.condition, filter_columns))

    children = [build_where(child, filter_columns) for child in node.conditions]
    return and_(*children) if node.op == "and" else or_(*children)


@router.post("/user", response_model=UserRead, status_code=201)
async def write_user(
    request: Request,
    user: UserCreate,
    # current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> UserRead:
    user_model = User(**user.model_dump(exclude={"password"}))

    if getattr(user, "password", None):
        user_model.hashed_password = ph.hash(user.password)

    db.add(user_model)

    try:
        await db.commit()

    except IntegrityError as error:
        await db.rollback()

        detail = str(getattr(error, "orig", ""))
        if "uq_user_email_not_deleted" in detail:
            field_name = "email"
        elif "uq_user_username_not_deleted" in detail:
            field_name = "username"
        elif "uq_user_phone_not_deleted" in detail:
            field_name = "phone number"
        else:
            raise BadRequestException("Unable to create the user. Please try again.")

        raise DuplicateValueException(f"{field_name} already exists")

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the user. Please try again later."
        )

    await db.refresh(user_model)

    return UserRead.model_validate(user_model)


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
        "data": [UserRead.model_validate(user) for user in users],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(crud_data=users_data, page=page, items_per_page=items_per_page)
    return response


@router.post("/users/search", response_model=PaginatedListResponse[UserRead])
async def search_users(
    request: Request,
    values: UserSearchRequest,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, Any]:
    filter_columns = {
        UserFilterField.USERNAME: User.username,
        UserFilterField.EMAIL: User.email,
        UserFilterField.PHONE_NUMBER: User.phone_number,
        UserFilterField.FIRST_NAME: User.first_name,
        UserFilterField.LAST_NAME: User.last_name,
        UserFilterField.COUNTRY: User.country,
        UserFilterField.CITY: User.city,
        UserFilterField.STATE_PROVINCE_REGION: User.state_province_region,
        UserFilterField.CREATED_AT: User.created_at,
    }

    sort_columns = {
        UserSortBy.USERNAME: User.username,
        UserSortBy.EMAIL: User.email,
        UserSortBy.PHONE_NUMBER: User.phone_number,
        UserSortBy.CREATED_AT: User.created_at,
    }

    where_clauses = [~User.is_deleted]

    if values.where is not None:
        where_clauses.append(build_where(values.where, filter_columns))

    sort_column = sort_columns.get(values.sort_by)
    if not sort_column:
        raise BadRequestException("Invalid sort_by field.")

    order_by_clause = sort_column.asc() if values.sort_order == SortOrder.ASC else sort_column.desc()

    db_users = (
        await db.execute(
            select(User)
            .where(*where_clauses)
            .order_by(order_by_clause)
            .offset(compute_offset(values.page, values.items_per_page))
            .limit(values.items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(*where_clauses)
        )
    ).scalar_one()

    users_data = {
        "data": [UserRead.model_validate(user) for user in db_users],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(
        crud_data=users_data,
        page=values.page,
        items_per_page=values.items_per_page
    )
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

    payload = values.model_dump(exclude_unset=True)
    geo_point = values.alert_center_geog if "alert_center_geog" in payload else None

    if "alert_center_geog" in payload:
        payload.pop("alert_center_geog")

        if geo_point is None:
            db_user.alert_center_geog = None
        else:
            point = Point(float(geo_point.longitude), float(geo_point.latitude))
            db_user.alert_center_geog = from_shape(point, srid=4326)

    for field, value in payload.items():
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

    all_profile_image_uuids: list[str] = []

    for pet in db_user.pets:
        pet.is_deleted = True
        pet.deleted_at = now

        for profile_image in pet.profile_images:
            profile_image.is_deleted = True
            profile_image.deleted_at = now
            all_profile_image_uuids.append(str(profile_image.uuid))

    try:
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting your account. Please try again later.",
        )

    if all_profile_image_uuids:
        try:
            await asyncio.to_thread(delete_embedding, "pet_profile_images", all_profile_image_uuids)
        except Exception as error:
            LOGGER.warning(
                f"Failed to delete embeddings for pet_profile_images {all_profile_image_uuids}: {error}"
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

    all_profile_image_uuids: list[str] = []
    for pet in db_user.pets:
        for profile_image in pet.profile_images:
            all_profile_image_uuids.append(str(profile_image.uuid))

    try:
        await db.delete(db_user)
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the user. Please try again later."
        )

    if all_profile_image_uuids:
        try:
            await asyncio.to_thread(delete_embedding, "pet_profile_images", all_profile_image_uuids)
        except Exception as error:
            LOGGER.warning(
                f"Failed to delete embeddings for pet_profile_images {all_profile_image_uuids}: {error}"
            )

    return {"message": "User deleted from the database"}
