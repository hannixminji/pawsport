from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..core.schemas import PersistentDeletion, TimestampSchema


class AttachmentFileType(str, Enum):
    PDF = "pdf"
    JPG = "jpg"
    JPEG = "jpeg"
    PNG = "png"


class PetVaccinationRecordAttachmentBase(BaseModel):
    object_key: Annotated[str, Field(min_length=1, max_length=1024, examples=["path/to/file.pdf"])]

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, v: str) -> str:
        if any(ch.isspace() for ch in v):
            raise ValueError("object_key must not contain whitespace")

        if "\\" in v or "'" in v or '"' in v:
            raise ValueError("object_key must not contain backslashes or quotes")

        if any(ch for ch in v if not ch.isprintable()):
            raise ValueError("object_key must not contain control characters")

        if v.startswith("/"):
            raise ValueError("object_key must be a relative path")

        if "//" in v:
            raise ValueError("object_key must not contain empty path segments")

        parts = v.split("/")
        if "." in parts or ".." in parts:
            raise ValueError("object_key must not contain '.' or '..' path segments")

        if v.endswith("/"):
            raise ValueError("object_key must not end with '/'")

        return v


class PetVaccinationRecordAttachment(TimestampSchema, PetVaccinationRecordAttachmentBase, PersistentDeletion):
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


class PetVaccinationRecordAttachmentCreate(PetVaccinationRecordAttachmentBase):
    model_config = ConfigDict(extra="forbid")


class PetVaccinationRecordAttachmentCreateInternal(PetVaccinationRecordAttachmentBase):
    vaccination_record_id: int
    file_name: str | None
    file_type: AttachmentFileType | None


class PetVaccinationRecordAttachmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[int | None, Field(gt=0, default=None)]
    object_key: Annotated[
        str | None,
        Field(min_length=1, max_length=1024, examples=["path/to/image.jpg"], default=None)
    ]

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, v: str | None) -> str | None:
        if v is None:
            return None

        if any(ch.isspace() for ch in v):
            raise ValueError("object_key must not contain whitespace")

        if "\\" in v or "'" in v or '"' in v:
            raise ValueError("object_key must not contain backslashes or quotes")

        if any(ch for ch in v if not ch.isprintable()):
            raise ValueError("object_key must not contain control characters")

        if v.startswith("/"):
            raise ValueError("object_key must be a relative path")

        if "//" in v:
            raise ValueError("object_key must not contain empty path segments")

        parts = v.split("/")
        if "." in parts or ".." in parts:
            raise ValueError("object_key must not contain '.' or '..' path segments")

        if v.endswith("/"):
            raise ValueError("object_key must not end with '/'")

        return v

    @model_validator(mode="after")
    def validate_existing_or_new_image(self):
        has_id = self.id is not None
        has_object_key = self.object_key is not None

        if has_id and has_object_key:
            raise ValueError("Provide either id (existing) or object_key (new), not both")

        if not has_id and not has_object_key:
            raise ValueError("Provide id (existing) or object_key (new)")

        return self


class PetVaccinationRecordAttachmentUpdateInternal(PetVaccinationRecordAttachmentUpdate):
    updated_at: datetime


class PetVaccinationRecordAttachmentDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime
