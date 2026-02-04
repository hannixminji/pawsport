import asyncio
import logging
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Union

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastcrud import PaginatedListResponse, compute_offset, paginated_response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, func, not_, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...api.dependencies import get_authenticated_superuser, get_authenticated_user
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from ...core.utils.cache import cache
from ...core.utils.google_cloud_storage import get_objects_metadata, is_objects_exist
from ...models.pet_inventory import InventoryType, PetInventory
from ...models.pet_inventory_image import InventoryImageFileType, PetInventoryImage
from ...models.user import User
from ...schemas.pet_inventory import PetInventoryCreateWithImages, PetInventoryRead, PetInventoryUpdateWithImages
from ...schemas.user import UserRead

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["pet_inventories"])


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class PetInventorySortBy(StrEnum):
    ITEM_NAME = "item_name"
    INVENTORY_TYPE = "inventory_type"
    EXPIRATION_DATE = "expiration_date"
    CREATED_AT = "created_at"


class FilterOp(StrEnum):
    EQ = "eq"
    ILIKE = "ilike"
    GTE = "gte"
    LTE = "lte"
    IN = "in"


class PetInventoryFilterField(StrEnum):
    ITEM_NAME = "item_name"
    INVENTORY_TYPE = "inventory_type"
    EXPIRATION_DATE = "expiration_date"


class WhereRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["rule"]
    field: PetInventoryFilterField
    op: FilterOp
    value: Any


class WhereGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["group"]
    op: Literal["and", "or"]
    conditions: list["WhereNode"] = Field(min_length=1, max_length=50)


class WhereNot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["not"]
    condition: "WhereNode"


WhereNode = Annotated[Union[WhereRule, WhereGroup, WhereNot], Field(discriminator="type")]


class PetInventorySearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1)
    items_per_page: int = Field(10, ge=1, le=100)

    sort_by: PetInventorySortBy = PetInventorySortBy.CREATED_AT
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


def _parse_iso_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    if not isinstance(value, str):
        raise BadRequestException("Date filter value must be YYYY-MM-DD.")

    try:
        return date.fromisoformat(value)
    except ValueError:
        raise BadRequestException("Invalid date format. Use YYYY-MM-DD.")


def build_where(node: WhereNode, filter_columns: dict[PetInventoryFilterField, Any]):  # noqa: C901
    if isinstance(node, WhereRule):
        column = filter_columns[node.field]
        value = node.value

        if node.field == PetInventoryFilterField.INVENTORY_TYPE:
            if node.op == FilterOp.EQ:
                if isinstance(value, str):
                    try:
                        value = InventoryType(value.lower())
                    except ValueError:
                        raise BadRequestException("Invalid inventory_type. Use 'food' or 'medicine'.")
                if not isinstance(value, InventoryType):
                    raise BadRequestException("Invalid inventory_type. Use 'food' or 'medicine'.")

            elif node.op == FilterOp.IN:
                if not isinstance(value, list) or not value:
                    raise BadRequestException("IN value must be a non-empty list.")
                converted: list[InventoryType] = []
                for item in value:
                    if not isinstance(item, str):
                        raise BadRequestException("inventory_type IN values must be strings.")
                    try:
                        converted.append(InventoryType(item.lower()))
                    except ValueError:
                        raise BadRequestException("Invalid inventory_type. Use 'food' or 'medicine'.")
                value = converted

            else:
                raise BadRequestException("inventory_type only supports eq or in.")

        if node.field == PetInventoryFilterField.EXPIRATION_DATE:
            if node.op not in {FilterOp.EQ, FilterOp.GTE, FilterOp.LTE}:
                raise BadRequestException("expiration_date only supports eq, gte, or lte.")
            value = _parse_iso_date(value)

        if node.field == PetInventoryFilterField.ITEM_NAME:
            if node.op not in {FilterOp.EQ, FilterOp.ILIKE, FilterOp.IN}:
                raise BadRequestException("item_name only supports eq, ilike, or in.")

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


def infer_file_type_from_object_key(object_key: str,) -> InventoryImageFileType:
    if "." not in object_key:
        raise BadRequestException("Invalid object_key (missing extension).")

    extension = object_key.rsplit(".", 1)[-1].lower()

    try:
        return InventoryImageFileType(extension)
    except ValueError:
        raise BadRequestException("Unsupported image type. Only JPG, JPEG, PNG are allowed.")


@router.post("/{username}/pet_inventory", response_model=PetInventoryRead, status_code=201)
async def write_pet_inventory(
    request: Request,
    username: str,
    inventory: PetInventoryCreateWithImages,
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> PetInventoryRead:
    db_user_id = (
        await db.execute(
            select(User.id)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    if current_user.id != db_user_id:
        raise ForbiddenException()

    object_keys = [image.object_key for image in inventory.images] if inventory.images else []

    if object_keys:
        exists_map = await asyncio.to_thread(is_objects_exist, object_keys)
        missing_object_keys = [object_key for object_key, exists in exists_map.items() if not exists]
        if missing_object_keys:
            raise BadRequestException(
                "Some image files might not have been uploaded. Please upload them and try again."
            )

    pet_inventory_model = PetInventory(
        **inventory.model_dump(exclude={"images"}),
        owner_id=db_user_id
    )
    db.add(pet_inventory_model)
    await db.flush()

    if inventory.images is not None:
        metadata_map = await asyncio.to_thread(get_objects_metadata, object_keys)

        for image in inventory.images:
            metadata = metadata_map.get(image.object_key) or {}

            file_type_raw = metadata.get("file_type")

            try:
                file_type_enum = InventoryImageFileType(str(file_type_raw).lower())
            except ValueError:
                raise BadRequestException("Image metadata has invalid file_type. Please re-upload the file.")

            image_model = PetInventoryImage(
                **image.model_dump(),
                inventory_id=pet_inventory_model.id,
                file_type=file_type_enum
            )
            db.add(image_model)
            pet_inventory_model.images.append(image_model)

    try:
        await db.commit()

    except IntegrityError as error:
        await db.rollback()

        if "uq_pet_inventory_owner_id_item_name_active" in str(getattr(error, "orig", "")):
            raise BadRequestException("This item already exists.")

        raise BadRequestException("Unable to create the item. Please try again.")

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the item. Please try again later."
        )

    await db.refresh(pet_inventory_model)

    return PetInventoryRead.model_validate(pet_inventory_model)


@router.post(
    "/{username}/pet_inventories/search",
    response_model=PaginatedListResponse[PetInventoryRead],
)
async def search_pet_inventories(
    request: Request,
    username: str,
    values: PetInventorySearchRequest,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, Any]:
    db_user_id = (
        await db.execute(
            select(User.id).where(
                User.username == username,
                ~User.is_deleted,
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    filter_columns = {
        PetInventoryFilterField.ITEM_NAME: PetInventory.item_name,
        PetInventoryFilterField.INVENTORY_TYPE: PetInventory.inventory_type,
        PetInventoryFilterField.EXPIRATION_DATE: PetInventory.expiration_date,
    }

    sort_columns = {
        PetInventorySortBy.ITEM_NAME: PetInventory.item_name,
        PetInventorySortBy.INVENTORY_TYPE: PetInventory.inventory_type,
        PetInventorySortBy.EXPIRATION_DATE: PetInventory.expiration_date,
        PetInventorySortBy.CREATED_AT: PetInventory.created_at,
    }

    where_clauses = [
        PetInventory.owner_id == db_user_id,
        ~PetInventory.is_deleted,
    ]

    if values.where is not None:
        where_clauses.append(build_where(values.where, filter_columns))

    sort_column = sort_columns.get(values.sort_by)
    if not sort_column:
        raise BadRequestException("Invalid sort_by field.")

    order_by_clause = sort_column.asc() if values.sort_order == SortOrder.ASC else sort_column.desc()

    db_pet_inventories = (
        await db.execute(
            select(PetInventory)
            .options(selectinload(PetInventory.images))
            .where(*where_clauses)
            .order_by(order_by_clause)
            .offset(compute_offset(values.page, values.items_per_page))
            .limit(values.items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(PetInventory)
            .where(*where_clauses)
        )
    ).scalar_one()

    pet_inventories_data = {
        "data": [PetInventoryRead.model_validate(item) for item in db_pet_inventories],
        "total_count": total_count,
    }

    response: dict[str, Any] = paginated_response(
        crud_data=pet_inventories_data,
        page=values.page,
        items_per_page=values.items_per_page,
    )
    return response


@router.get("/{username}/pet_inventories", response_model=PaginatedListResponse[PetInventoryRead])
@cache(
    key_prefix="{username}_pet_inventories:page_{page}:items_per_page:{items_per_page}",
    resource_id_name="username",
    expiration=60,
)
async def read_pet_inventories(
    request: Request,
    username: str,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    page: int = 1,
    items_per_page: int = 10,
) -> dict[str, Any]:
    db_user_id = (
        await db.execute(
            select(User.id)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    db_pet_inventories = (
        await db.execute(
            select(PetInventory)
            .options(selectinload(PetInventory.images))
            .where(
                PetInventory.owner_id == db_user_id,
                ~PetInventory.is_deleted
            )
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(PetInventory)
            .where(
                PetInventory.owner_id == db_user_id,
                ~PetInventory.is_deleted
            )
        )
    ).scalar_one()

    pet_inventories_data = {
        "data": [PetInventoryRead.model_validate(inventory) for inventory in db_pet_inventories],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(
        crud_data=pet_inventories_data,
        page=page,
        items_per_page=items_per_page
    )
    return response


@router.get("/{username}/pet_inventory/{id}", response_model=PetInventoryRead)
@cache(key_prefix="{username}_pet_inventory_cache", resource_id_name="id")
async def read_pet_inventory(
    request: Request,
    username: str,
    id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> PetInventoryRead:
    db_user_id = (
        await db.execute(
            select(User.id)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    db_pet_inventory = (
        await db.execute(
            select(PetInventory)
            .options(selectinload(PetInventory.images))
            .where(
                PetInventory.id == id,
                PetInventory.owner_id == db_user_id,
                ~PetInventory.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_inventory:
        raise NotFoundException("Item not found")

    return PetInventoryRead.model_validate(db_pet_inventory)


@router.patch("/{username}/pet_inventory/{id}")
@cache(
    "{username}_pet_inventory_cache",
    resource_id_name="id",
    pattern_to_invalidate_extra=["{username}_pet_inventories:*"],
)
async def patch_pet_inventory(
    request: Request,
    username: str,
    id: int,
    values: PetInventoryUpdateWithImages,
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    db_user_id = (
        await db.execute(
            select(User.id)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    if current_user.id != db_user_id:
        raise ForbiddenException()

    db_pet_inventory = (
        await db.execute(
            select(PetInventory)
            .options(selectinload(PetInventory.images))
            .where(
                PetInventory.id == id,
                PetInventory.owner_id == db_user_id,
                ~PetInventory.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_inventory:
        raise NotFoundException("Item not found")

    for field, value in values.model_dump(exclude_unset=True, exclude={"images"}).items():
        setattr(db_pet_inventory, field, value)

    object_keys = [
        image.object_key
        for image in values.images
        if getattr(image, "object_key", None) is not None
    ] if values.images else []

    metadata_map: dict[str, dict[str, str]] = {}

    if object_keys:
        exists_map = await asyncio.to_thread(is_objects_exist, object_keys)
        missing_object_keys = [object_key for object_key, exists in exists_map.items() if not exists]
        if missing_object_keys:
            raise BadRequestException(
                "Some image files might not have been uploaded. Please upload them and try again."
            )

        metadata_map = await asyncio.to_thread(get_objects_metadata, object_keys)

    existing_images = {image.id: image for image in db_pet_inventory.images}

    if values.images is not None:
        image_ids = {
            image.id
            for image in values.images
            if getattr(image, "id", None) is not None
        }

        invalid_ids = image_ids - set(existing_images.keys())
        if invalid_ids:
            raise NotFoundException("Some images do not exist.")

        if len(image_ids) + len(object_keys) > 5:
            raise BadRequestException("You can only have up to 5 images per inventory item.")

        deleted_image_ids = list(set(existing_images) - image_ids)
        now = datetime.now(UTC)
        for image_id in deleted_image_ids:
            image = existing_images[image_id]
            image.is_deleted = True
            image.deleted_at = now

        for image in values.images:
            if getattr(image, "id", None):
                existing_image = existing_images[image.id]
                existing_image.sort_order = image.sort_order

            elif getattr(image, "object_key", None):
                metadata = metadata_map.get(image.object_key) or {}
                file_type_raw = metadata.get("file_type")

                try:
                    file_type_enum = InventoryImageFileType(str(file_type_raw).lower())
                except ValueError:
                    raise BadRequestException("Image metadata has invalid file_type. Please re-upload the file.")

                new_image = PetInventoryImage(
                    inventory_id=db_pet_inventory.id,
                    object_key=image.object_key,
                    sort_order=image.sort_order,
                    file_type=file_type_enum
                )
                db.add(new_image)
                db_pet_inventory.images.append(new_image)

    db_pet_inventory.updated_at = datetime.now(UTC)

    try:
        await db.commit()

    except IntegrityError as error:
        await db.rollback()

        if "uq_pet_inventory_owner_id_item_name_active" in str(getattr(error, "orig", "")):
            raise BadRequestException("This item already exists.")

        if "uq_pet_inventory_image_inventory_id_sort_order_active" in str(getattr(error, "orig", "")):
            raise BadRequestException("Please arrange the images in a valid order.")

        raise BadRequestException("Unable to update the item. Please try again.")

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the item. Please try again later."
        )

    return {"message": "Item updated"}


@router.delete("/{username}/pet_inventory/{id}")
@cache(
    "{username}_pet_inventory_cache",
    resource_id_name="id",
    to_invalidate_extra={"{username}_pet_inventories": "{username}"},
)
async def erase_pet_inventory(
    request: Request,
    username: str,
    id: int,
    current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    db_user_id = (
        await db.execute(
            select(User.id)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    if current_user.id != db_user_id:
        raise ForbiddenException()

    db_pet_inventory = (
        await db.execute(
            select(PetInventory)
            .where(
                PetInventory.id == id,
                PetInventory.owner_id == db_user_id,
                ~PetInventory.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_inventory:
        raise NotFoundException("Item not found")

    now = datetime.now(UTC)
    db_pet_inventory.is_deleted = True
    db_pet_inventory.deleted_at = now
    db.add(db_pet_inventory)

    try:
        await db.execute(
            update(PetInventoryImage)
            .where(
                PetInventoryImage.inventory_id == db_pet_inventory.id,
                ~PetInventoryImage.is_deleted
            )
            .values(
                is_deleted=True,
                deleted_at=now
            )
        )

        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the item. Please try again later."
        )

    return {"message": "Item deleted"}


@router.delete("/{username}/db_pet_inventory/{id}", dependencies=[Depends(get_authenticated_superuser)])
@cache(
    "{username}_pet_inventory_cache",
    resource_id_name="id",
    to_invalidate_extra={"{username}_pet_inventories": "{username}"},
)
async def erase_db_pet_inventory(
    request: Request,
    username: str,
    id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    db_user_id = (
        await db.execute(
            select(User.id)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    db_pet_inventory = (
        await db.execute(
            select(PetInventory)
            .where(
                PetInventory.id == id,
                PetInventory.owner_id == db_user_id,
                ~PetInventory.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_inventory:
        raise NotFoundException("Item not found")

    try:
        await db.delete(db_pet_inventory)
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the item. Please try again later."
        )

    return {"message": "Item deleted from the database"}
