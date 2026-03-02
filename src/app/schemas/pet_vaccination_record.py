from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..core.enums import VaccineType
from ..core.schemas import PersistentDeletion, TimestampSchema
from .pet_vaccination_record_attachment import (
    PetVaccinationRecordAttachmentCreate,
    PetVaccinationRecordAttachmentRead,
    PetVaccinationRecordAttachmentUpdate,
)


class PetVaccinationRecordBase(BaseModel):
    vaccine_name: Annotated[str, Field(min_length=3, max_length=255, examples=["Rabies"])]
    vaccine_type: Annotated[VaccineType, Field(examples=[VaccineType.CORE])]
    administered_date: Annotated[date, Field(examples=["2025-01-10"])]
    next_due_date: Annotated[date | None, Field(examples=["2026-01-10"], default=None)]

    @field_validator("vaccine_name", mode="before")
    @classmethod
    def normalize_vaccine_name(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("vaccine_type", mode="before")
    @classmethod
    def normalize_vaccine_type(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("administered_date")
    @classmethod
    def no_future_date_administered(cls, v: date):
        if v > date.today():
            raise ValueError("administered_date cannot be in the future")
        return v

    @model_validator(mode="after")
    def validate_next_due_after_administered(self):
        if self.next_due_date is not None:
            if self.next_due_date < self.administered_date:
                raise ValueError("next_due_date must be the same as or after administered_date")
        return self


class PetVaccinationRecord(TimestampSchema, PetVaccinationRecordBase, PersistentDeletion):
    pet_id: int


class PetVaccinationRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pet_id: int
    vaccine_name: str
    vaccine_type: VaccineType
    administered_date: date
    attachments: list[PetVaccinationRecordAttachmentRead]
    created_at: datetime
    next_due_date: date | None



class PetVaccinationRecordCreate(PetVaccinationRecordBase):
    model_config = ConfigDict(extra="forbid")


class PetVaccinationRecordCreateWithAttachments(PetVaccinationRecordCreate):
    attachments: Annotated[list[PetVaccinationRecordAttachmentCreate] | None, Field(default=None, max_length=5)]

    @field_validator("attachments", mode="after")
    @classmethod
    def validate_attachments(cls, attachments):
        if attachments is None:
            return attachments

        if not attachments:
            return attachments

        object_keys = [attachment.object_key for attachment in attachments]
        if len(object_keys) != len(set(object_keys)):
            raise ValueError("attachment object_key must be unique")

        sort_orders = [attachment.sort_order for attachment in attachments]
        if len(sort_orders) != len(set(sort_orders)):
            raise ValueError("attachment sort_order must be unique")

        return attachments


class PetVaccinationRecordUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vaccine_name: Annotated[str | None, Field(min_length=3, max_length=255, examples=["Rabies"], default=None)]
    vaccine_type: Annotated[VaccineType | None, Field(examples=[VaccineType.CORE], default=None)]
    administered_date: Annotated[date | None, Field(examples=["2025-01-10"], default=None)]
    next_due_date: Annotated[date | None, Field(examples=["2026-01-10"], default=None)]

    @field_validator("vaccine_name", mode="before")
    @classmethod
    def normalize_vaccine_name(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("vaccine_type", mode="before")
    @classmethod
    def normalize_vaccine_type(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("administered_date")
    @classmethod
    def no_future_date_administered(cls, v: date | None):
        if v is not None and v > date.today():
            raise ValueError("administered_date cannot be in the future")
        return v

    @model_validator(mode="after")
    def validate_next_due_after_administered(self):
        if self.administered_date is not None and self.next_due_date is not None:
            if self.next_due_date < self.administered_date:
                raise ValueError("next_due_date must be the same as or after administered_date")
        return self


class PetVaccinationRecordUpdateWithAttachments(PetVaccinationRecordUpdate):
    attachments: Annotated[list[PetVaccinationRecordAttachmentUpdate] | None, Field(default=None, max_length=5)]

    @field_validator("attachments", mode="after")
    @classmethod
    def validate_attachments(cls, attachments):
        if attachments is None:
            return attachments

        if not attachments:
            return attachments

        attachment_ids = [attachment.id for attachment in attachments if attachment.id is not None]
        if len(attachment_ids) != len(set(attachment_ids)):
            raise ValueError("duplicate attachment ids are not allowed")

        object_keys = [attachment.object_key for attachment in attachments if attachment.object_key is not None]
        if len(object_keys) != len(set(object_keys)):
            raise ValueError("duplicate object keys are not allowed")

        sort_orders = [attachment.sort_order for attachment in attachments]
        if len(sort_orders) != len(set(sort_orders)):
            raise ValueError("attachment sort_order must be unique")

        return attachments


class PetVaccinationRecordBulkDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: Annotated[set[int], Field(min_length=1, max_length=100)]

    @field_validator("ids", mode="before")
    @classmethod
    def validate_ids(cls, v):
        if not isinstance(v, list):
            raise ValueError("ids must be a list")

        if len(v) != len(set(v)):
            raise ValueError("ids must not contain duplicates")

        if any(id_ < 1 for id_ in v):
            raise ValueError("each id must be >= 1")

        return v
