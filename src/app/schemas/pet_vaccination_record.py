from datetime import date, datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema
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

    @field_validator("vaccine_name")
    @classmethod
    def normalize_vaccine_name(cls, v: str) -> str:
        return v.strip()

    @field_validator("next_due_date")
    @classmethod
    def validate_next_due_after_administered(cls, v: date | None, info):
        administered = info.data.get("date_administered")
        if v is None or administered is None:
            return v
        if v < administered:
            raise ValueError("next_due_date must be the same as or after date_administered")
        return v


class PetVaccinationRecord(TimestampSchema, PetVaccinationRecordBase, UUIDSchema, PersistentDeletion):
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


class PetVaccinationRecordCreateInternal(PetVaccinationRecordCreate):
    pet_id: int


class PetVaccinationRecordCreateWithAttachments(PetVaccinationRecordCreate):
    attachments: Annotated[list[PetVaccinationRecordAttachmentCreate] | None, Field(default=None, max_length=5)]


class PetVaccinationRecordUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vaccine_name: Annotated[str | None, Field(min_length=3, max_length=255, examples=["Rabies"], default=None)]
    vaccine_type: Annotated[VaccineType | None, Field(examples=[VaccineType.CORE], default=None)]
    date_administered: Annotated[date | None, Field(examples=["2025-01-10"], default=None)]
    next_due_date: Annotated[date | None, Field(examples=["2026-01-10"], default=None)]

    @field_validator("vaccine_name")
    @classmethod
    def normalize_vaccine_name(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v


class PetVaccinationRecordUpdateWithAttachments(PetVaccinationRecordUpdate):
    attachments: Annotated[list[PetVaccinationRecordAttachmentUpdate] | None, Field(default=None, max_length=5)]


class PetVaccinationRecordUpdateInternal(PetVaccinationRecordUpdate):
    updated_at: datetime


class PetVaccinationRecordDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime
