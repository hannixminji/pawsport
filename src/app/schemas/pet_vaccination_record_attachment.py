from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema


class AttachmentFileType(str, Enum):
    PDF = "pdf"
    JPG = "jpg"
    JPEG = "jpeg"
    PNG = "png"


class PetVaccinationRecordAttachmentBase(BaseModel):
    object_key: Annotated[str, Field(min_length=1, max_length=1024, examples=["path/to/file.pdf"])]


class PetVaccinationRecordAttachment(
    TimestampSchema, PetVaccinationRecordAttachmentBase, UUIDSchema, PersistentDeletion
):
    vaccination_record_id: int
    file_name: str | None
    file_type: AttachmentFileType | None


class PetVaccinationRecordAttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vaccination_record_id: int
    attachment_url: str
    file_name: str | None
    file_type: AttachmentFileType | None


class PetVaccinationRecordAttachmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_key: Annotated[str, Field(min_length=1, max_length=1024, examples=["path/to/file.pdf"])]


class PetVaccinationRecordAttachmentCreateInternal(PetVaccinationRecordAttachmentCreate):
    vaccination_record_id: int


class PetVaccinationRecordAttachmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_key: Annotated[str | None, Field(min_length=1, max_length=1024, examples=["path/to/file.pdf"], default=None)]


class PetVaccinationRecordAttachmentUpdateInternal(PetVaccinationRecordAttachmentUpdate):
    updated_at: datetime


class PetVaccinationRecordAttachmentDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime
