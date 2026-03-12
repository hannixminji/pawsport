import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar, Union

from sqlalchemy import any_, delete, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..core.enums import ActorType, AttachmentMimeType
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
from ..models.pet import Pet
from ..models.pet_vaccination_record import PetVaccinationRecord
from ..models.pet_vaccination_record_attachment import PetVaccinationRecordAttachment
from ..schemas.pet_vaccination_record import (
    PetVaccinationRecordCreateWithAttachments,
    PetVaccinationRecordRead,
    PetVaccinationRecordUpdateWithAttachments,
)
from ..schemas.pet_vaccination_record_attachment import (
    PetVaccinationRecordAttachmentCreate,
    PetVaccinationRecordAttachmentUpdate,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PetVaccinationRecordService:
    db: AsyncSession

    MAX_ATTACHMENTS_PER_RECORD: ClassVar[int] = 5
    MAX_TOTAL_ATTACHMENT_SIZE_BYTES: ClassVar[int] = 20 * 1024 * 1024

    MOBILE_SEARCH_BLACKLIST_COLUMNS: ClassVar[frozenset[str]] = frozenset({
        "id",
        "pet_id",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ADMIN_SEARCH_BLACKLIST_COLUMNS: ClassVar[frozenset[str]] = frozenset({
        "id",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ALLOWED_FILTER_OPERATORS_BY_COLUMN: ClassVar[dict] = {
        "pet_id": frozenset({
            FilterOp.EQ,
        }),
        "vaccine_name": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
        }),
        "vaccine_type": frozenset({
            FilterOp.EQ,
            FilterOp.IN,
        }),
        "administered_date": frozenset({
            FilterOp.LT,
            FilterOp.LTE,
            FilterOp.GT,
            FilterOp.GTE,
        }),
        "next_due_date": frozenset({
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
    SEARCH_SORTABLE_COLUMNS: ClassVar[set[str]] = {
        "vaccine_name",
        "administered_date",
        "next_due_date",
        "created_at",
    }

    @staticmethod
    def _is_unique_constraint_violation(error: IntegrityError, constraint_name: str) -> bool:
        original_exception = getattr(error, "orig", None)
        if original_exception is None:
            return False

        return constraint_name in str(original_exception)

    async def _get_owned_pet_owner_id(self, actor: Actor, pet_id: int) -> int | None:
        return (
            await self.db.execute(
                select(Pet.owner_id)
                .where(
                    Pet.id == pet_id,
                    Pet.owner_id == actor.id,
                    Pet.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

    async def _require_pet_ownership(self, actor: Actor, pet_id: int) -> None:
        owner_id = await self._get_owned_pet_owner_id(actor, pet_id)
        if owner_id is None:
            raise NotFoundError("Pet not found.")

    async def _require_pet_access(self, actor: Actor, pet_id: int) -> None:
        if actor.actor_type not in (ActorType.ADMIN_USER, ActorType.MOBILE_USER):
            raise ForbiddenError("You do not have permission to access this pet.")

        if actor.actor_type == ActorType.MOBILE_USER:
            await self._require_pet_ownership(actor, pet_id)

    async def _get_owned_vaccination_record_id(self, actor: Actor, vaccination_record_id: int) -> int | None:
        return (
            await self.db.execute(
                select(PetVaccinationRecord.id)
                .join(Pet, Pet.id == PetVaccinationRecord.pet_id)
                .where(
                    Pet.owner_id == actor.id,
                    Pet.is_deleted.is_(False),
                    PetVaccinationRecord.id == vaccination_record_id,
                    PetVaccinationRecord.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

    async def _require_vaccination_record_ownership(self, actor: Actor, vaccination_record_id: int) -> None:
        result = await self._get_owned_vaccination_record_id(actor, vaccination_record_id)
        if result is None:
            raise NotFoundError("Vaccination record not found.")

    async def _require_vaccination_record_access(self, actor: Actor, vaccination_record_id: int) -> None:
        if actor.actor_type not in (ActorType.ADMIN_USER, ActorType.MOBILE_USER):
            raise ForbiddenError("You do not have permission to access this vaccination record.")

        if actor.actor_type == ActorType.MOBILE_USER:
            await self._require_vaccination_record_ownership(actor, vaccination_record_id)

    async def _get_vaccination_record(
        self,
        vaccination_record_id: int,
        actor: Actor | None = None,
        with_attachments: bool = False,
    ) -> PetVaccinationRecord | None:
        query = select(PetVaccinationRecord)

        if with_attachments:
            query = query.options(selectinload(PetVaccinationRecord.attachments))

        query = query.where(
            PetVaccinationRecord.id == vaccination_record_id,
            PetVaccinationRecord.is_deleted.is_(False),
        )

        if actor is not None and actor.actor_type == ActorType.MOBILE_USER:
            query = (
                query
                .join(Pet, Pet.id == PetVaccinationRecord.pet_id)
                .where(
                    Pet.owner_id == actor.id,
                    Pet.is_deleted.is_(False),
                )
            )

        return (await self.db.execute(query)).scalar_one_or_none()

    async def _check_object_keys_exist(self, object_keys: list[str]) -> dict[str, dict[str, str | int]]:
        if not object_keys:
            return {}

        object_existence_map = await asyncio.to_thread(is_objects_exist, object_keys)
        missing_object_keys = [object_key for object_key, exists in object_existence_map.items() if not exists]

        if missing_object_keys:
            raise InvalidInputError(
                "Some attachment files might not have been uploaded. Please upload them and try again."
            )

        return await asyncio.to_thread(get_objects_metadata, object_keys)

    def _build_new_attachment(
        self,
        vaccination_record_id: int,
        attachment: Union[PetVaccinationRecordAttachmentCreate, PetVaccinationRecordAttachmentUpdate],
        attachment_object_metadata_map: dict,
    ) -> PetVaccinationRecordAttachment:
        metadata = attachment_object_metadata_map.get(attachment.object_key, {})
        mime_type_raw = metadata.get("mime_type")
        original_filename = metadata.get("original_filename", "")

        if not mime_type_raw:
            raise InvalidInputError("Attachment metadata missing mime_type. Please re-upload the file.")

        try:
            mime_type_enum = AttachmentMimeType(mime_type_raw.lower())
        except ValueError:
            raise InvalidInputError("Attachment metadata has invalid mime_type. Please re-upload the file.")

        return PetVaccinationRecordAttachment(
            vaccination_record_id=vaccination_record_id,
            object_key=attachment.object_key,
            sort_order=attachment.sort_order,
            original_filename=original_filename,
            mime_type=mime_type_enum,
        )

    def _soft_delete_removed_attachments(
        self,
        existing_attachments: dict,
        attachment_ids_from_input: set,
    ) -> None:
        attachments_to_delete = set(existing_attachments.keys()) - attachment_ids_from_input

        now = datetime.now(UTC)
        for attachment_id in attachments_to_delete:
            existing_attachments[attachment_id].is_deleted = True
            existing_attachments[attachment_id].deleted_at = now

    def _check_attachment_count_limit(
        self,
        attachment_ids_from_input: set[int],
        new_attachments: list[PetVaccinationRecordAttachmentCreate],
    ) -> None:
        if len(attachment_ids_from_input) + len(new_attachments) > self.MAX_ATTACHMENTS_PER_RECORD:
            raise InvalidInputError(
                f"You can only have up to {self.MAX_ATTACHMENTS_PER_RECORD} attachments per vaccination record."
            )

    def _check_total_attachment_size(
        self,
        new_attachments: list[PetVaccinationRecordAttachmentCreate],
        attachment_object_metadata_map: dict[str, dict[str, str | int]],
    ) -> None:
        total_size = sum(
            int(attachment_object_metadata_map.get(attachment.object_key, {}).get("_size", 0))
            for attachment in new_attachments
        )

        if total_size > self.MAX_TOTAL_ATTACHMENT_SIZE_BYTES:
            limit_mb = self.MAX_TOTAL_ATTACHMENT_SIZE_BYTES // (1024 * 1024)
            raise InvalidInputError(f"Total size of uploaded attachments exceeds the {limit_mb}MB limit.")

    def _check_attachment_ids_exist(
        self,
        attachment_ids_from_input: set[int],
        db_existing_attachments: dict[int, PetVaccinationRecordAttachment],
    ) -> None:
        unknown_attachment_ids = attachment_ids_from_input - db_existing_attachments.keys()
        if unknown_attachment_ids:
            raise NotFoundError("One or more attachments you're trying to keep were not found.")

    def _update_existing_attachments(
        self,
        existing_attachments_from_input: list[PetVaccinationRecordAttachmentUpdate],
        db_existing_attachments: dict[int, PetVaccinationRecordAttachment],
    ) -> None:
        for attachment in existing_attachments_from_input:
            db_existing_attachments[attachment.id].sort_order = attachment.sort_order

    async def _add_new_attachments(
        self,
        db_record: PetVaccinationRecord,
        new_attachments: list[PetVaccinationRecordAttachmentCreate],
        attachment_object_metadata_map: dict[str, dict[str, str | int]],
    ) -> None:
        for attachment in new_attachments:
            new_attachment = self._build_new_attachment(db_record.id, attachment, attachment_object_metadata_map)
            self.db.add(new_attachment)
            db_record.attachments.append(new_attachment)

    async def _apply_attachment_updates(
        self,
        db_record: PetVaccinationRecord,
        attachments: list[Union[PetVaccinationRecordAttachmentCreate, PetVaccinationRecordAttachmentUpdate]],
    ) -> None:
        new_attachments = [attachment for attachment in attachments if getattr(attachment, "id", None) is None]
        existing_attachments_from_input = [
            attachment for attachment in attachments if getattr(attachment, "id", None) is not None
        ]
        attachment_ids_from_input: set[int] = {attachment.id for attachment in existing_attachments_from_input}

        self._check_attachment_count_limit(attachment_ids_from_input, new_attachments)

        db_existing_attachments: dict[int, PetVaccinationRecordAttachment] = {
            attachment.id: attachment for attachment in db_record.attachments if not attachment.is_deleted
        }

        self._check_attachment_ids_exist(attachment_ids_from_input, db_existing_attachments)

        attachment_object_metadata_map = await self._check_object_keys_exist(
            [attachment.object_key for attachment in new_attachments]
        )

        self._check_total_attachment_size(new_attachments, attachment_object_metadata_map)

        self._update_existing_attachments(existing_attachments_from_input, db_existing_attachments)
        await self._add_new_attachments(db_record, new_attachments, attachment_object_metadata_map)
        self._soft_delete_removed_attachments(db_existing_attachments, attachment_ids_from_input)

    async def create(
        self,
        *,
        actor: Actor,
        pet_id: int,
        vaccination_record_input: PetVaccinationRecordCreateWithAttachments,
    ) -> PetVaccinationRecordRead:
        await self._require_pet_access(actor, pet_id)

        vaccination_record_model = PetVaccinationRecord(
            **vaccination_record_input.model_dump(exclude={"attachments"}),
            pet_id=pet_id,
        )
        self.db.add(vaccination_record_model)
        await self.db.flush()

        vaccination_record_model = await self.db.scalar(
            select(PetVaccinationRecord)
            .options(selectinload(PetVaccinationRecord.attachments))
            .where(PetVaccinationRecord.id == vaccination_record_model.id)
        )

        if vaccination_record_input.attachments:
            await self._apply_attachment_updates(vaccination_record_model, vaccination_record_input.attachments)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_pet_vaccination_record_attachment_sort_order_active"):
                raise InvalidInputError("Please arrange the attachments in a valid order.")

            raise InvalidInputError("Unable to create the vaccination record.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to create the vaccination record. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to create the vaccination record."
            ) from error

        result = await self.db.scalar(
            select(PetVaccinationRecord)
            .options(selectinload(PetVaccinationRecord.attachments))
            .where(PetVaccinationRecord.id == vaccination_record_model.id)
        )

        return PetVaccinationRecordRead.model_validate(result)

    async def search(
        self,
        *,
        actor: Actor,
        search_request: SearchRequest,
        user_id: int | None = None,
        pet_id: int | None = None,
    ) -> PaginatedResponse[PetVaccinationRecordRead]:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to search vaccination records.")

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
                select(PetVaccinationRecord)
                .join(Pet, Pet.id == PetVaccinationRecord.pet_id)
                .where(
                    Pet.owner_id == user_id,
                    Pet.is_deleted.is_(False),
                    PetVaccinationRecord.is_deleted.is_(False),
                )
            )
        else:
            base_query = select(PetVaccinationRecord).where(PetVaccinationRecord.is_deleted.is_(False))

        if pet_id is not None:
            base_query = base_query.where(PetVaccinationRecord.pet_id == pet_id)

        engine = SearchEngine(
            db=self.db,
            model=PetVaccinationRecord,
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
            serializer=PetVaccinationRecordRead.model_validate,
        )

        return PaginatedResponse[PetVaccinationRecordRead](
            data=result.data,
            total_count=result.total_count,
            has_more=(result.page * result.items_per_page) < result.total_count,
            page=result.page,
            items_per_page=result.items_per_page,
        )

    async def get_vaccination_records(
        self,
        *,
        actor: Actor,
        page: int,
        items_per_page: int,
        user_id: int | None = None,
        pet_id: int | None = None,
    ) -> PaginatedResponse[PetVaccinationRecordRead]:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view vaccination records.")

        if actor.actor_type == ActorType.MOBILE_USER:
            user_id = actor.id

        base_query = (
            select(PetVaccinationRecord)
            .join(Pet, Pet.id == PetVaccinationRecord.pet_id)
            .where(
                Pet.is_deleted.is_(False),
                PetVaccinationRecord.is_deleted.is_(False),
            )
        )

        if user_id is not None:
            base_query = base_query.where(Pet.owner_id == user_id)

        if pet_id is not None:
            base_query = base_query.where(PetVaccinationRecord.pet_id == pet_id)

        db_vaccination_records = (
            await self.db.execute(
                base_query
                .options(selectinload(PetVaccinationRecord.attachments))
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

        return PaginatedResponse[PetVaccinationRecordRead](
            data=[
                PetVaccinationRecordRead.model_validate(vaccination_record)
                for vaccination_record in db_vaccination_records
            ],
            total_count=total_count,
            has_more=(page * items_per_page) < total_count,
            page=page,
            items_per_page=items_per_page,
        )

    async def get_vaccination_record(
        self,
        *,
        actor: Actor,
        vaccination_record_id: int,
    ) -> PetVaccinationRecordRead:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view this vaccination record.")

        db_vaccination_record = await self._get_vaccination_record(vaccination_record_id, actor, with_attachments=True)
        if db_vaccination_record is None:
            raise NotFoundError("Vaccination record not found.")

        return PetVaccinationRecordRead.model_validate(db_vaccination_record)

    async def update(
        self,
        *,
        actor: Actor,
        vaccination_record_id: int,
        vaccination_record_input: PetVaccinationRecordUpdateWithAttachments,
    ) -> None:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to update this vaccination record.")

        db_vaccination_record = await self._get_vaccination_record(vaccination_record_id, actor, with_attachments=True)
        if db_vaccination_record is None:
            raise NotFoundError("Vaccination record not found.")

        if vaccination_record_input.attachments is not None:
            await self._apply_attachment_updates(db_vaccination_record, vaccination_record_input.attachments)

        apply_partial_update(
            target=db_vaccination_record,
            input=vaccination_record_input,
            exclude={"attachments"},
        )

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_pet_vaccination_record_attachment_sort_order_active"):
                raise InvalidInputError("Please arrange the attachments in a valid order.")

            raise InvalidInputError("Unable to update the vaccination record.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update the vaccination record. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update the vaccination record."
            ) from error

    async def soft_delete(
        self,
        *,
        actor: Actor,
        vaccination_record_id: int,
    ) -> None:
        await self._require_vaccination_record_access(actor, vaccination_record_id)

        statement_vaccination_record = (
            update(PetVaccinationRecord)
            .where(
                PetVaccinationRecord.id == vaccination_record_id,
                PetVaccinationRecord.is_deleted.is_(False),
            )
            .values(
                deleted_at=func.now(),
                is_deleted=True,
            )
        )

        statement_attachments = (
            update(PetVaccinationRecordAttachment)
            .where(
                PetVaccinationRecordAttachment.vaccination_record_id == vaccination_record_id,
                PetVaccinationRecordAttachment.is_deleted.is_(False),
            )
            .values(
                deleted_at=func.now(),
                is_deleted=True,
            )
        )

        try:
            await self.db.execute(statement_vaccination_record)
            await self.db.execute(statement_attachments)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to delete the vaccination record. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete the vaccination record."
            ) from error

    async def bulk_soft_delete(
        self,
        *,
        actor: Actor,
        vaccination_record_ids: set[int],
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to delete vaccination records in bulk.")

        if not vaccination_record_ids:
            return

        statement_vaccination_records = (
            update(PetVaccinationRecord)
            .where(
                PetVaccinationRecord.id == any_(list(vaccination_record_ids)),
                PetVaccinationRecord.is_deleted.is_(False),
            )
            .values(
                deleted_at=func.now(),
                is_deleted=True,
            )
        )

        statement_attachments = (
            update(PetVaccinationRecordAttachment)
            .where(
                PetVaccinationRecordAttachment.vaccination_record_id == any_(list(vaccination_record_ids)),
                PetVaccinationRecordAttachment.is_deleted.is_(False),
            )
            .values(
                deleted_at=func.now(),
                is_deleted=True,
            )
        )

        try:
            await self.db.execute(statement_vaccination_records)
            await self.db.execute(statement_attachments)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to delete vaccination records. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete vaccination records."
            ) from error

    async def hard_delete(
        self,
        *,
        actor: Actor,
        vaccination_record_id: int,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete the vaccination record.")

        statement = (
            delete(PetVaccinationRecord)
            .where(PetVaccinationRecord.id == vaccination_record_id)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete the vaccination record. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete the vaccination record."
            ) from error

    async def bulk_hard_delete(
        self,
        *,
        actor: Actor,
        vaccination_record_ids: set[int],
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete vaccination records.")

        if not vaccination_record_ids:
            return

        statement = (
            delete(PetVaccinationRecord)
            .where(PetVaccinationRecord.id == any_(list(vaccination_record_ids)))
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete vaccination records. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete vaccination records."
            ) from error
