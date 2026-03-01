import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Union

from sqlalchemy import any_, delete, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..core.enums import ActorType, MimeType
from ..core.exceptions.authorization_exceptions import ForbiddenError
from ..core.exceptions.db_exceptions import NonTransientDatabaseError, TransientDatabaseError
from ..core.exceptions.domain_exceptions import InvalidInputError, NotFoundError
from ..core.schemas import Actor, PaginatedResponse
from ..core.search_engine.engine import SearchEngine
from ..core.search_engine.enums import FilterOp
from ..core.search_engine.schemas import SearchRequest
from ..core.utils.google_cloud_storage import get_objects_metadata, is_objects_exist
from ..core.utils.pagination import compute_offset
from ..core.utils.update import apply_partial_update
from ..models.pet_inventory import PetInventory
from ..models.pet_inventory_image import PetInventoryImage
from ..schemas.pet_inventory import PetInventoryCreateWithImages, PetInventoryRead, PetInventoryUpdateWithImages
from ..schemas.pet_inventory_image import PetInventoryImageCreate, PetInventoryImageUpdate

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PetInventoryService:
    db: AsyncSession

    MAX_IMAGES_PER_INVENTORY = 5

    MOBILE_SEARCH_BLACKLIST_COLUMNS = frozenset({
        "id",
        "owner_id",
        "quantity",
        "unit",
        "notes",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ADMIN_SEARCH_BLACKLIST_COLUMNS = frozenset({
        "id",
        "quantity",
        "unit",
        "notes",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ALLOWED_FILTER_OPERATORS_BY_COLUMN = {
        "owner_id": frozenset({
            FilterOp.EQ,
        }),
        "name": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
        }),
        "inventory_type": frozenset({
            FilterOp.EQ,
            FilterOp.IN,
        }),
        "expiration_date": frozenset({
            FilterOp.LT,
            FilterOp.LTE,
            FilterOp.GT,
            FilterOp.GTE,
        }),
        "created_at": frozenset({
            FilterOp.LT,
            FilterOp.LTE,
            FilterOp.GT,
            FilterOp.GTE,
        }),
    }
    SEARCH_SORTABLE_COLUMNS = {
        "name",
        "expiration_date",
        "created_at",
    }

    def _is_unique_constraint_violation(self, error: IntegrityError, constraint_name: str) -> bool:
        original_exception = getattr(error, "orig", None)
        if original_exception is None:
            return False

        return constraint_name in str(original_exception)

    async def _get_owned_inventory_owner_id(self, actor: Actor, inventory_id: int) -> int | None:
        return (
            await self.db.execute(
                select(PetInventory.owner_id)
                .where(
                    PetInventory.id == inventory_id,
                    PetInventory.owner_id == actor.id,
                    PetInventory.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

    async def _require_inventory_ownership(self, actor: Actor, inventory_id: int) -> None:
        owner_id = await self._get_owned_inventory_owner_id(actor, inventory_id)
        if owner_id is None:
            raise NotFoundError("Inventory item not found.")

    async def _require_inventory_access(self, actor: Actor, inventory_id: int) -> None:
        if actor.actor_type not in (ActorType.ADMIN_USER, ActorType.MOBILE_USER):
            raise ForbiddenError("You do not have permission to access this inventory item.")

        if actor.actor_type == ActorType.MOBILE_USER:
            await self._require_inventory_ownership(actor, inventory_id)

    async def _get_inventory(
        self,
        inventory_id: int,
        actor: Actor | None = None,
        with_images: bool = False,
    ) -> PetInventory | None:
        query = select(PetInventory)

        if with_images:
            query = query.options(selectinload(PetInventory.images))

        query = query.where(
            PetInventory.id == inventory_id,
            PetInventory.is_deleted.is_(False),
        )

        if actor is not None and actor.actor_type == ActorType.MOBILE_USER:
            query = query.where(PetInventory.owner_id == actor.id)

        return (await self.db.execute(query)).scalar_one_or_none()

    async def _check_object_keys_exist(self, object_keys: list[str]) -> dict[str, dict[str, str]]:
        if not object_keys:
            return {}

        object_existence_map = await asyncio.to_thread(is_objects_exist, object_keys)
        missing_object_keys = [object_key for object_key, exists in object_existence_map.items() if not exists]

        if missing_object_keys:
            raise InvalidInputError("Some image files might not have been uploaded. Please upload them and try again.")

        return await asyncio.to_thread(get_objects_metadata, object_keys)

    def _build_new_image(
        self,
        inventory_id: int,
        image: Union[PetInventoryImageCreate, PetInventoryImageUpdate],
        image_object_metadata_map: dict,
    ) -> PetInventoryImage:
        metadata = image_object_metadata_map.get(image.object_key, {})
        mime_type_raw = metadata.get("mime_type")

        if not mime_type_raw:
            raise InvalidInputError("Image metadata missing mime_type. Please re-upload the file.")

        try:
            mime_type_enum = MimeType(mime_type_raw.lower())
        except ValueError:
            raise InvalidInputError("Image metadata has invalid mime_type. Please re-upload the file.")

        return PetInventoryImage(
            inventory_id=inventory_id,
            object_key=image.object_key,
            sort_order=image.sort_order,
            mime_type=mime_type_enum,
        )

    def _soft_delete_removed_images(
        self,
        existing_images: dict,
        image_ids_from_input: set,
    ) -> None:
        images_to_delete = set(existing_images.keys()) - image_ids_from_input

        now = datetime.now(UTC)
        for image_id in images_to_delete:
            existing_images[image_id].is_deleted = True
            existing_images[image_id].deleted_at = now

    def _check_image_count_limit(
        self,
        image_ids_from_input: set[int],
        new_images: list[PetInventoryImageCreate],
    ) -> None:
        if len(image_ids_from_input) + len(new_images) > self.MAX_IMAGES_PER_INVENTORY:
            raise InvalidInputError(
                f"You can only have up to {self.MAX_IMAGES_PER_INVENTORY} images per inventory item."
            )

    def _check_image_ids_exist(
        self,
        image_ids_from_input: set[int],
        db_existing_images: dict[int, PetInventoryImage],
    ) -> None:
        unknown_image_ids = image_ids_from_input - db_existing_images.keys()
        if unknown_image_ids:
            raise NotFoundError("One or more images you're trying to keep were not found.")

    def _update_existing_images(
        self,
        existing_images_from_input: list[PetInventoryImageUpdate],
        db_existing_images: dict[int, PetInventoryImage],
    ) -> None:
        for image in existing_images_from_input:
            db_existing_images[image.id].sort_order = image.sort_order

    async def _add_new_images(
        self,
        db_item: PetInventory,
        new_images: list[PetInventoryImageCreate],
        image_object_metadata_map: dict[str, dict[str, str]],
    ) -> None:
        for image in new_images:
            new_image = self._build_new_image(db_item.id, image, image_object_metadata_map)
            self.db.add(new_image)
            db_item.images.append(new_image)

    async def _apply_image_updates(
        self,
        db_item: PetInventory,
        images: list[Union[PetInventoryImageCreate, PetInventoryImageUpdate]],
    ) -> None:
        new_images = [image for image in images if getattr(image, "id", None) is None]
        existing_images_from_input = [image for image in images if getattr(image, "id", None) is not None]
        image_ids_from_input: set[int] = {image.id for image in existing_images_from_input}

        self._check_image_count_limit(image_ids_from_input, new_images)

        db_existing_images: dict[int, PetInventoryImage] = {
            image.id: image for image in db_item.images if not image.is_deleted
        }

        self._check_image_ids_exist(image_ids_from_input, db_existing_images)

        image_object_metadata_map = await self._check_object_keys_exist(
            [image.object_key for image in new_images]
        )

        self._update_existing_images(existing_images_from_input, db_existing_images)
        await self._add_new_images(db_item, new_images, image_object_metadata_map)
        self._soft_delete_removed_images(db_existing_images, image_ids_from_input)

    async def create(
        self,
        *,
        actor: Actor,
        user_id: int,
        inventory_input: PetInventoryCreateWithImages,
    ) -> PetInventoryRead:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to create an inventory item.")

        if actor.actor_type == ActorType.MOBILE_USER:
            user_id = actor.id

        inventory_model = PetInventory(
            **inventory_input.model_dump(exclude={"images"}),
            owner_id=user_id,
        )
        self.db.add(inventory_model)
        await self.db.flush()

        if inventory_input.images:
            await self._apply_image_updates(inventory_model, inventory_input.images)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_pet_inventory_owner_id_name_active"):
                raise InvalidInputError("An item with this name already exists.")

            if self._is_unique_constraint_violation(error, "uq_pet_inventory_image_inventory_id_sort_order_active"):
                raise InvalidInputError("Please arrange the images in a valid order.")

            raise InvalidInputError("Unable to create the inventory item.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to create the inventory item. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to create the inventory item."
            ) from error

        await self.db.refresh(inventory_model, ["images"])
        return PetInventoryRead.model_validate(inventory_model)

    async def search(
        self,
        *,
        actor: Actor,
        search_request: SearchRequest,
        user_id: int | None = None,
    ) -> PaginatedResponse[PetInventoryRead]:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to search inventory.")

        if actor.actor_type == ActorType.MOBILE_USER:
            user_id = actor.id

        blacklisted = (
            self.MOBILE_SEARCH_BLACKLIST_COLUMNS
            if actor.actor_type == ActorType.MOBILE_USER
            else self.ADMIN_SEARCH_BLACKLIST_COLUMNS
        )

        if (
            actor.actor_type == ActorType.MOBILE_USER
            or (actor.actor_type == ActorType.ADMIN_USER and user_id is not None)
        ):
            base_query = (
                select(PetInventory)
                .where(
                    PetInventory.owner_id == user_id,
                    PetInventory.is_deleted.is_(False),
                )
            )
        else:
            base_query = select(PetInventory).where(PetInventory.is_deleted.is_(False))

        engine = SearchEngine(
            db=self.db,
            model=PetInventory,
            blacklisted_columns=blacklisted,
            allowed_ops=self.ALLOWED_FILTER_OPERATORS_BY_COLUMN,
            column_order_map=None,
            sortable_columns=self.SEARCH_SORTABLE_COLUMNS,
            max_in_list_size=100,
            max_depth=1,
        )

        result = await engine.search(
            base_query=base_query,
            values=search_request,
            serializer=PetInventoryRead.model_validate,
        )

        return PaginatedResponse[PetInventoryRead](
            data=result.data,
            total_count=result.total_count,
            has_more=(result.page * result.items_per_page) < result.total_count,
            page=result.page,
            items_per_page=result.items_per_page,
        )

    async def get_inventory_items(
        self,
        *,
        actor: Actor,
        page: int,
        items_per_page: int,
        user_id: int | None = None,
    ) -> PaginatedResponse[PetInventoryRead]:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view inventory items.")

        if actor.actor_type == ActorType.MOBILE_USER:
            user_id = actor.id

        base_query = (
            select(PetInventory)
            .where(PetInventory.is_deleted.is_(False))
        )

        if user_id is not None:
            base_query = base_query.where(PetInventory.owner_id == user_id)

        db_items = (
            await self.db.execute(
                base_query
                .options(selectinload(PetInventory.images))
                .offset(compute_offset(page, items_per_page))
                .limit(items_per_page)
            )
        ).scalars().all()

        total_count = (
            await self.db.execute(
                select(func.count())
                .select_from(base_query.subquery())
            )
        ).scalar_one()

        return PaginatedResponse[PetInventoryRead](
            data=[PetInventoryRead.model_validate(item) for item in db_items],
            total_count=total_count,
            has_more=(page * items_per_page) < total_count,
            page=page,
            items_per_page=items_per_page,
        )

    async def get_inventory(
        self,
        *,
        actor: Actor,
        inventory_id: int,
    ) -> PetInventoryRead:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view this inventory item.")

        db_item = await self._get_inventory(inventory_id, actor, with_images=True)
        if db_item is None:
            raise NotFoundError("Inventory item not found.")

        return PetInventoryRead.model_validate(db_item)

    async def update(
        self,
        *,
        actor: Actor,
        inventory_id: int,
        inventory_input: PetInventoryUpdateWithImages,
    ) -> None:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to update this inventory item.")

        db_item = await self._get_inventory(inventory_id, actor, with_images=True)
        if db_item is None:
            raise NotFoundError("Inventory item not found.")

        if inventory_input.images is not None:
            await self._apply_image_updates(db_item, inventory_input.images)

        apply_partial_update(
            target=db_item,
            input=inventory_input,
            exclude={"images"},
        )

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_pet_inventory_owner_id_name_active"):
                raise InvalidInputError("An item with this name already exists.")

            if self._is_unique_constraint_violation(error, "uq_pet_inventory_image_inventory_id_sort_order_active"):
                raise InvalidInputError("Please arrange the images in a valid order.")

            raise InvalidInputError("Unable to update the inventory item.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update the inventory item. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update the inventory item."
            ) from error

    async def soft_delete(
        self,
        *,
        actor: Actor,
        inventory_id: int,
    ) -> None:
        await self._require_inventory_access(actor, inventory_id)

        statement_inventory = (
            update(PetInventory)
            .where(
                PetInventory.id == inventory_id,
                PetInventory.is_deleted.is_(False),
            )
            .values(
                deleted_at=func.now(),
                is_deleted=True,
            )
        )

        statement_images = (
            update(PetInventoryImage)
            .where(
                PetInventoryImage.inventory_id == inventory_id,
                PetInventoryImage.is_deleted.is_(False),
            )
            .values(
                deleted_at=func.now(),
                is_deleted=True,
            )
        )

        try:
            await self.db.execute(statement_inventory)
            await self.db.execute(statement_images)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to delete the inventory item. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete the inventory item."
            ) from error

    async def bulk_soft_delete(
        self,
        *,
        actor: Actor,
        inventory_ids: set[int],
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to delete inventory items in bulk.")

        if not inventory_ids:
            return

        statement_inventory = (
            update(PetInventory)
            .where(
                PetInventory.id == any_(list(inventory_ids)),
                PetInventory.is_deleted.is_(False),
            )
            .values(
                deleted_at=func.now(),
                is_deleted=True,
            )
        )

        statement_images = (
            update(PetInventoryImage)
            .where(
                PetInventoryImage.inventory_id == any_(list(inventory_ids)),
                PetInventoryImage.is_deleted.is_(False),
            )
            .values(
                deleted_at=func.now(),
                is_deleted=True,
            )
        )

        try:
            await self.db.execute(statement_inventory)
            await self.db.execute(statement_images)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to delete inventory items. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete inventory items."
            ) from error

    async def hard_delete(
        self,
        *,
        actor: Actor,
        inventory_id: int,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete an inventory item.")

        statement = (
            delete(PetInventory)
            .where(PetInventory.id == inventory_id)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete the inventory item. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete the inventory item."
            ) from error

    async def bulk_hard_delete(
        self,
        *,
        actor: Actor,
        inventory_ids: set[int],
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete inventory items.")

        if not inventory_ids:
            return

        statement = (
            delete(PetInventory)
            .where(PetInventory.id == any_(list(inventory_ids)))
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete inventory items. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete inventory items."
            ) from error
