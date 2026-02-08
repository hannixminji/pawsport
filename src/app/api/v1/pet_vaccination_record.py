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
from ...models.pet import Pet
from ...models.pet_vaccination_record import PetVaccinationRecord, VaccineType
from ...models.pet_vaccination_record_attachment import AttachmentFileType, PetVaccinationRecordAttachment
from ...models.user import User
from ...schemas.pet_vaccination_record import (
    PetVaccinationRecordCreateWithAttachments,
    PetVaccinationRecordRead,
    PetVaccinationRecordUpdateWithAttachments,
)
from ...schemas.user import UserRead

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["pet_vaccination_records"])


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class VaccinationRecordSortBy(StrEnum):
    VACCINE_NAME = "vaccine_name"
    DATE_ADMINISTERED = "date_administered"
    NEXT_DUE_DATE = "next_due_date"
    CREATED_AT = "created_at"


class FilterOp(StrEnum):
    EQ = "eq"
    ILIKE = "ilike"
    GTE = "gte"
    LTE = "lte"
    IN = "in"


class VaccinationRecordFilterField(StrEnum):
    VACCINE_NAME = "vaccine_name"
    VACCINE_TYPE = "vaccine_type"
    DATE_ADMINISTERED = "date_administered"
    NEXT_DUE_DATE = "next_due_date"


class WhereRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["rule"]
    field: VaccinationRecordFilterField
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


class PetVaccinationRecordSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1)
    items_per_page: int = Field(10, ge=1, le=100)

    sort_by: VaccinationRecordSortBy = VaccinationRecordSortBy.DATE_ADMINISTERED
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


def build_where(node: WhereNode, filter_columns: dict[VaccinationRecordFilterField, Any]):  # noqa: C901
    if isinstance(node, WhereRule):
        column = filter_columns[node.field]
        value = node.value

        if node.field == VaccinationRecordFilterField.VACCINE_TYPE:
            if node.op == FilterOp.EQ:
                if isinstance(value, str):
                    try:
                        value = VaccineType(value.lower())
                    except ValueError:
                        raise BadRequestException("Invalid vaccine_type. Use 'core' or 'non_core'.")
                if not isinstance(value, VaccineType):
                    raise BadRequestException("Invalid vaccine_type. Use 'core' or 'non_core'.")

            elif node.op == FilterOp.IN:
                if not isinstance(value, list) or not value:
                    raise BadRequestException("IN value must be a non-empty list.")
                converted: list[VaccineType] = []
                for item in value:
                    if not isinstance(item, str):
                        raise BadRequestException("vaccine_type IN values must be strings.")
                    try:
                        converted.append(VaccineType(item.lower()))
                    except ValueError:
                        raise BadRequestException("Invalid vaccine_type. Use 'core' or 'non_core'.")
                value = converted

            else:
                raise BadRequestException("vaccine_type only supports eq or in.")

        if node.field in {VaccinationRecordFilterField.DATE_ADMINISTERED, VaccinationRecordFilterField.NEXT_DUE_DATE}:
            if node.op in {FilterOp.EQ, FilterOp.GTE, FilterOp.LTE}:
                if isinstance(value, str):
                    try:
                        value = date.fromisoformat(value)
                    except ValueError:
                        raise BadRequestException("Invalid date format. Use YYYY-MM-DD.")
                if not isinstance(value, date):
                    raise BadRequestException("Date filter value must be YYYY-MM-DD.")

        if node.field == VaccinationRecordFilterField.VACCINE_NAME:
            if node.op not in {FilterOp.EQ, FilterOp.ILIKE, FilterOp.IN}:
                raise BadRequestException("vaccine_name only supports eq, ilike, or in.")

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


@router.post("/{username}/pet/{pet_id}/vaccination_record", response_model=PetVaccinationRecordRead, status_code=201)
async def write_pet_vaccination_record(
    request: Request,
    username: str,
    pet_id: int,
    vaccination_record: PetVaccinationRecordCreateWithAttachments,
    # current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> PetVaccinationRecordRead:
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

    # if current_user.id != db_user_id:
    #     raise ForbiddenException()

    db_pet_id = (
        await db.execute(
            select(Pet.id)
            .where(
                Pet.id == pet_id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_id:
        raise NotFoundException("Pet not found")

    object_keys = [
        attachment.object_key
        for attachment in vaccination_record.attachments
    ] if vaccination_record.attachments else []

    if object_keys:
        exists_map = await asyncio.to_thread(is_objects_exist, object_keys)
        missing_object_keys = [object_key for object_key, exists in exists_map.items() if not exists]
        if missing_object_keys:
            raise BadRequestException(
                "Some attachment files might not have been uploaded. Please upload them and try again."
            )

    pet_vaccination_record_model = PetVaccinationRecord(
        **vaccination_record.model_dump(exclude={"attachments"}),
        pet_id=db_pet_id
    )
    db.add(pet_vaccination_record_model)
    await db.flush()

    if vaccination_record.attachments is not None:
        metadata_map = await asyncio.to_thread(get_objects_metadata, object_keys)

        for attachment in vaccination_record.attachments:
            metadata = metadata_map.get(attachment.object_key) or {}

            original_filename = metadata.get("original_filename")
            file_type_raw = metadata.get("file_type")

            try:
                file_type_enum = AttachmentFileType(file_type_raw.lower())
            except ValueError:
                raise BadRequestException("Attachment metadata has invalid file_type. Please re-upload the file.")

            attachment_model = PetVaccinationRecordAttachment(
                **attachment.model_dump(),
                vaccination_record_id=pet_vaccination_record_model.id,
                file_name=original_filename,
                file_type=file_type_enum
            )
            db.add(attachment_model)

    try:
        await db.commit()

    except IntegrityError as error:
        await db.rollback()

        if "uq_pet_vaccination_record_pet_id_vaccine_name_active" in str(getattr(error, "orig", "")):
            raise BadRequestException("This vaccine record already exists for this pet.")

        raise BadRequestException("Unable to create the vaccination record. Please try again.")

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the vaccination record. Please try again later."
        )

    await db.refresh(pet_vaccination_record_model)

    return PetVaccinationRecordRead.model_validate(pet_vaccination_record_model)


@router.post(
    "/{username}/pet/{pet_id}/vaccination_records/search",
    response_model=PaginatedListResponse[PetVaccinationRecordRead]
)
async def search_pet_vaccination_records(
    request: Request,
    username: str,
    pet_id: int,
    values: PetVaccinationRecordSearchRequest,
    db: Annotated[AsyncSession, Depends(async_get_db)],
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

    db_pet_id = (
        await db.execute(
            select(Pet.id)
            .where(
                Pet.id == pet_id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_id:
        raise NotFoundException("Pet not found")

    filter_columns = {
        VaccinationRecordFilterField.VACCINE_NAME: PetVaccinationRecord.vaccine_name,
        VaccinationRecordFilterField.VACCINE_TYPE: PetVaccinationRecord.vaccine_type,
        VaccinationRecordFilterField.DATE_ADMINISTERED: PetVaccinationRecord.date_administered,
        VaccinationRecordFilterField.NEXT_DUE_DATE: PetVaccinationRecord.next_due_date,
    }

    sort_columns = {
        VaccinationRecordSortBy.VACCINE_NAME: PetVaccinationRecord.vaccine_name,
        VaccinationRecordSortBy.DATE_ADMINISTERED: PetVaccinationRecord.date_administered,
        VaccinationRecordSortBy.NEXT_DUE_DATE: PetVaccinationRecord.next_due_date,
        VaccinationRecordSortBy.CREATED_AT: PetVaccinationRecord.created_at,
    }

    where_clauses = [
        PetVaccinationRecord.pet_id == db_pet_id,
        ~PetVaccinationRecord.is_deleted
    ]

    if values.where is not None:
        where_clauses.append(build_where(values.where, filter_columns))

    sort_column = sort_columns.get(values.sort_by)
    if not sort_column:
        raise BadRequestException("Invalid sort_by field.")

    order_by_clause = sort_column.asc() if values.sort_order == SortOrder.ASC else sort_column.desc()

    db_pet_vaccination_records = (
        await db.execute(
            select(PetVaccinationRecord)
            .options(selectinload(PetVaccinationRecord.attachments))
            .where(*where_clauses)
            .order_by(order_by_clause)
            .offset(compute_offset(values.page, values.items_per_page))
            .limit(values.items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(PetVaccinationRecord)
            .where(*where_clauses)
        )
    ).scalar_one()

    pet_vaccination_records_data = {
        "data": [PetVaccinationRecordRead.model_validate(record) for record in db_pet_vaccination_records],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(
        crud_data=pet_vaccination_records_data,
        page=values.page,
        items_per_page=values.items_per_page
    )
    return response


@router.get(
    "/{username}/pet/{pet_id}/vaccination_records",
    response_model=PaginatedListResponse[PetVaccinationRecordRead]
)
@cache(
    key_prefix="{username}_pet_{pet_id}_vaccination_records:page_{page}:items_per_page:{items_per_page}",
    resource_id_name="pet_id",
    expiration=60,
)
async def read_pet_vaccination_records(
    request: Request,
    username: str,
    pet_id: int,
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

    db_pet_id = (
        await db.execute(
            select(Pet.id)
            .where(
                Pet.id == pet_id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_id:
        raise NotFoundException("Pet not found")

    db_pet_vaccination_records = (
        await db.execute(
            select(PetVaccinationRecord)
            .options(selectinload(PetVaccinationRecord.attachments))
            .where(
                PetVaccinationRecord.pet_id == db_pet_id,
                ~PetVaccinationRecord.is_deleted
            )
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(PetVaccinationRecord)
            .where(
                PetVaccinationRecord.pet_id == db_pet_id,
                ~PetVaccinationRecord.is_deleted
            )
        )
    ).scalar_one()

    pet_vaccination_records_data = {
        "data": [PetVaccinationRecordRead.model_validate(record) for record in db_pet_vaccination_records],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(
        crud_data=pet_vaccination_records_data,
        page=page,
        items_per_page=items_per_page
    )
    return response


@router.get("/{username}/pet/{pet_id}/vaccination_record/{id}", response_model=PetVaccinationRecordRead)
@cache(key_prefix="{username}_pet_{pet_id}_vaccination_record_cache", resource_id_name="id")
async def read_pet_vaccination_record(
    request: Request,
    username: str,
    pet_id: int,
    id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> PetVaccinationRecordRead:
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

    db_pet_id = (
        await db.execute(
            select(Pet.id)
            .where(
                Pet.id == pet_id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_id:
        raise NotFoundException("Pet not found")

    db_pet_vaccination_record = (
        await db.execute(
            select(PetVaccinationRecord)
            .options(selectinload(PetVaccinationRecord.attachments))
            .where(
                PetVaccinationRecord.id == id,
                PetVaccinationRecord.pet_id == db_pet_id,
                ~PetVaccinationRecord.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_vaccination_record:
        raise NotFoundException("Vaccination record not found")

    return PetVaccinationRecordRead.model_validate(db_pet_vaccination_record)


@router.patch("/{username}/pet/{pet_id}/vaccination_record/{id}")
@cache(
    "{username}_pet_{pet_id}_vaccination_record_cache",
    resource_id_name="id",
    pattern_to_invalidate_extra=["{username}_pet_{pet_id}_vaccination_records:*"],
)
async def patch_pet_vaccination_record(
    request: Request,
    username: str,
    pet_id: int,
    id: int,
    values: PetVaccinationRecordUpdateWithAttachments,
    # current_user: Annotated[UserRead, Depends(get_authenticated_user)],
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

    # if current_user.id != db_user_id:
    #     raise ForbiddenException()

    db_pet_id = (
        await db.execute(
            select(Pet.id)
            .where(
                Pet.id == pet_id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_id:
        raise NotFoundException("Pet not found")

    db_pet_vaccination_record = (
        await db.execute(
            select(PetVaccinationRecord)
            .options(selectinload(PetVaccinationRecord.attachments))
            .where(
                PetVaccinationRecord.id == id,
                PetVaccinationRecord.pet_id == db_pet_id,
                ~PetVaccinationRecord.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_vaccination_record:
        raise NotFoundException("Vaccination record not found")

    payload = values.model_dump(exclude_unset=True, exclude={"attachments"})

    date_administered = payload.get("date_administered", db_pet_vaccination_record.date_administered)
    next_due_date = payload.get("next_due_date", db_pet_vaccination_record.next_due_date)

    if date_administered is not None and next_due_date is not None and next_due_date < date_administered:
        raise BadRequestException("next_due_date must be on or after date_administered")

    for field, value in payload.items():
        setattr(db_pet_vaccination_record, field, value)

    object_keys = [
        attachment.object_key
        for attachment in values.attachments
        if getattr(attachment, "object_key", None) is not None
    ] if values.attachments else []

    metadata_map: dict[str, dict[str, str]] = {}

    if object_keys:
        exists_map = await asyncio.to_thread(is_objects_exist, object_keys)
        missing_object_keys = [object_key for object_key, exists in exists_map.items() if not exists]
        if missing_object_keys:
            raise BadRequestException(
                "Some attachment files might not have been uploaded. Please upload them and try again."
            )

        metadata_map = await asyncio.to_thread(get_objects_metadata, object_keys)

    existing_attachments = {attachment.id: attachment for attachment in db_pet_vaccination_record.attachments}

    if values.attachments is not None:
        attachment_ids = {
            attachment.id
            for attachment in values.attachments
            if getattr(attachment, "id", None) is not None
        }

        invalid_ids = attachment_ids - set(existing_attachments.keys())
        if invalid_ids:
            raise NotFoundException("Some attachments do not exist.")

        deleted_attachment_ids = list(set(existing_attachments) - attachment_ids)
        now = datetime.now(UTC)
        for attachment_id in deleted_attachment_ids:
            attachment = existing_attachments[attachment_id]
            attachment.is_deleted = True
            attachment.deleted_at = now

        for attachment in values.attachments:
            if getattr(attachment, "object_key", None):
                metadata = metadata_map.get(attachment.object_key) or {}
                filename = metadata.get("original_filename")
                file_type_raw = metadata.get("file_type")

                try:
                    file_type_enum = AttachmentFileType(str(file_type_raw).lower())
                except ValueError:
                    raise BadRequestException("Attachment metadata has invalid file_type. Please re-upload the file.")

                new_attachment = PetVaccinationRecordAttachment(
                    vaccination_record_id=db_pet_vaccination_record.id,
                    object_key=attachment.object_key,
                    file_name=filename,
                    file_type=file_type_enum
                )
                db.add(new_attachment)
                db_pet_vaccination_record.attachments.append(new_attachment)

    db_pet_vaccination_record.updated_at = datetime.now(UTC)

    try:
        await db.commit()

    except IntegrityError as error:
        await db.rollback()

        if "uq_pet_vaccination_record_pet_id_vaccine_name_active" in str(getattr(error, "orig", "")):
            raise BadRequestException("This vaccine record already exists for this pet.")

        raise BadRequestException("Unable to update the vaccination record. Please try again.")

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the vaccination record. Please try again later."
        )

    return {"message": "Vaccination record updated"}


@router.delete("/{username}/pet/{pet_id}/vaccination_record/{id}")
@cache(
    "{username}_pet_{pet_id}_vaccination_record_cache",
    resource_id_name="id",
    to_invalidate_extra={"{username}_pet_{pet_id}_vaccination_records": "{pet_id}"},
)
async def erase_pet_vaccination_record(
    request: Request,
    username: str,
    pet_id: int,
    id: int,
    # current_user: Annotated[UserRead, Depends(get_authenticated_user)],
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

    # if current_user.id != db_user_id:
    #     raise ForbiddenException()

    db_pet_id = (
        await db.execute(
            select(Pet.id)
            .where(
                Pet.id == pet_id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_id:
        raise NotFoundException("Pet not found")

    db_pet_vaccination_record = (
        await db.execute(
            select(PetVaccinationRecord)
            .where(
                PetVaccinationRecord.id == id,
                PetVaccinationRecord.pet_id == db_pet_id,
                ~PetVaccinationRecord.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_vaccination_record:
        raise NotFoundException("Vaccination record not found")

    now = datetime.now(UTC)
    db_pet_vaccination_record.is_deleted = True
    db_pet_vaccination_record.deleted_at = now
    db.add(db_pet_vaccination_record)

    try:
        await db.execute(
            update(PetVaccinationRecordAttachment)
            .where(
                PetVaccinationRecordAttachment.vaccination_record_id == db_pet_vaccination_record.id,
                ~PetVaccinationRecordAttachment.is_deleted
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
            detail="An unexpected error occurred while deleting the vaccination record. Please try again later."
        )

    return {"message": "Vaccination record deleted"}


@router.delete(
    "/{username}/pet/{pet_id}/db_pet_vaccination_record/{id}",
    dependencies=[Depends(get_authenticated_superuser)]
)
@cache(
    "{username}_pet_{pet_id}_vaccination_record_cache",
    resource_id_name="id",
    to_invalidate_extra={"{username}_pet_{pet_id}_vaccination_records": "{pet_id}"},
)
async def erase_db_pet_vaccination_record(
    request: Request,
    username: str,
    pet_id: int,
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

    db_pet_id = (
        await db.execute(
            select(Pet.id)
            .where(
                Pet.id == pet_id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_id:
        raise NotFoundException("Pet not found")

    db_pet_vaccination_record = (
        await db.execute(
            select(PetVaccinationRecord)
            .where(
                PetVaccinationRecord.id == id,
                PetVaccinationRecord.pet_id == db_pet_id,
                ~PetVaccinationRecord.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet_vaccination_record:
        raise NotFoundException("Vaccination record not found")

    try:
        await db.delete(db_pet_vaccination_record)
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the vaccination record. Please try again later."
        )

    return {"message": "Vaccination record deleted from the database"}
