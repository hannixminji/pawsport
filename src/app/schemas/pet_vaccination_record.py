from datetime import date, datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..core.schemas import PersistentDeletion, TimestampSchema
from .pet_vaccination_record_attachment import (
    PetVaccinationRecordAttachmentCreate,
    PetVaccinationRecordAttachmentRead,
    PetVaccinationRecordAttachmentUpdate,
)


class VaccineType(str, Enum):
    CORE = "core"
    NON_CORE = "non_core"


class PetVaccinationRecordBase(BaseModel):
    vaccine_name: Annotated[str, Field(min_length=3, max_length=255, examples=["Rabies"])]
    vaccine_type: Annotated[VaccineType, Field(examples=[VaccineType.CORE])]
    date_administered: Annotated[date, Field(examples=["2025-01-10"])]
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

    @field_validator("date_administered")
    @classmethod
    def no_future_date_administered(cls, v: date):
        if v > date.today():
            raise ValueError("date_administered cannot be in the future")
        return v

    @model_validator(mode="after")
    def validate_next_due_after_date_administered(self):
        if self.next_due_date is not None:
            if self.next_due_date < self.date_administered:
                raise ValueError("next_due_date must be the same as or after date_administered")
        return self


class PetVaccinationRecord(TimestampSchema, PetVaccinationRecordBase, PersistentDeletion):
    pet_id: int


class PetVaccinationRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pet_id: int
    vaccine_name: str
    vaccine_type: VaccineType
    date_administered: date
    attachments: list[PetVaccinationRecordAttachmentRead]
    next_due_date: date | None


class PetVaccinationRecordCreate(PetVaccinationRecordBase):
    model_config = ConfigDict(extra="forbid")


class PetVaccinationRecordCreateInternal(PetVaccinationRecordBase):
    pet_id: int


class PetVaccinationRecordCreateWithAttachments(PetVaccinationRecordCreate):
    attachments: Annotated[list[PetVaccinationRecordAttachmentCreate] | None, Field(default=None, max_length=5)]


class PetVaccinationRecordUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vaccine_name: Annotated[str | None, Field(min_length=3, max_length=255, examples=["Rabies"], default=None)]
    vaccine_type: Annotated[VaccineType | None, Field(examples=[VaccineType.CORE], default=None)]
    date_administered: Annotated[date | None, Field(examples=["2025-01-10"], default=None)]
    next_due_date: Annotated[date | None, Field(examples=["2026-01-10"], default=None)]

    @field_validator("vaccine_name", mode="before")
    @classmethod
    def normalize_vaccine_name(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v

    @field_validator("vaccine_type", mode="before")
    @classmethod
    def normalize_vaccine_type(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("date_administered")
    @classmethod
    def no_future_date_administered(cls, v: date | None):
        if v is not None and v > date.today():
            raise ValueError("date_administered cannot be in the future")
        return v

    @model_validator(mode="after")
    def validate_next_due_after_date_administered(self):
        if self.date_administered is not None and self.next_due_date is not None:
            if self.next_due_date < self.date_administered:
                raise ValueError("next_due_date must be the same as or after date_administered")
        return self


class PetVaccinationRecordUpdateWithAttachments(PetVaccinationRecordUpdate):
    attachments: Annotated[list[PetVaccinationRecordAttachmentUpdate] | None, Field(default=None, max_length=5)]


class PetVaccinationRecordUpdateInternal(PetVaccinationRecordUpdate):
    updated_at: datetime


class PetVaccinationRecordDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime
