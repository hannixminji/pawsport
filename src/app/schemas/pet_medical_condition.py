from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.enums import MedicalConditionSeverity, MedicalConditionStatus
from ..core.schemas import PersistentDeletion, TimestampSchema


class PetMedicalConditionBase(BaseModel):
    condition_name: Annotated[str, Field(min_length=3, max_length=255, examples=["Hip Dysplasia"])]
    severity: Annotated[MedicalConditionSeverity, Field(examples=[MedicalConditionSeverity.MODERATE])]
    condition_status: Annotated[
        MedicalConditionStatus,
        Field(
            examples=[MedicalConditionStatus.ACTIVE],
        ),
    ]
    diagnosis_date: Annotated[date | None, Field(examples=["2024-05-12"], default=None)]
    notes: Annotated[str | None, Field(max_length=2000, examples=["Requires regular checkups"], default=None)]

    @field_validator("condition_name", mode="before")
    @classmethod
    def normalize_condition_name(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("severity", "condition_status", mode="before")
    @classmethod
    def normalize_enum_fields(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("diagnosis_date")
    @classmethod
    def validate_diagnosis_date(cls, v: date | None):
        if v is not None and v > date.today():
            raise ValueError("diagnosis_date cannot be in the future")
        return v

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class PetMedicalCondition(TimestampSchema, PetMedicalConditionBase, PersistentDeletion):
    pet_id: int


class PetMedicalConditionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pet_id: int
    condition_name: str
    severity: MedicalConditionSeverity
    condition_status: MedicalConditionStatus
    created_at: datetime
    diagnosis_date: date | None
    notes: str | None


class PetMedicalConditionCreate(PetMedicalConditionBase):
    model_config = ConfigDict(extra="forbid")


class PetMedicalConditionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condition_name: Annotated[str | None, Field(min_length=3, max_length=255, examples=["Hip Dysplasia"], default=None)]
    severity: Annotated[
        MedicalConditionSeverity | None,
        Field(
            examples=[MedicalConditionSeverity.MODERATE],
            default=None,
        ),
    ]
    condition_status: Annotated[
        MedicalConditionStatus | None,
        Field(
            examples=[MedicalConditionStatus.ACTIVE],
            default=None,
        ),
    ]
    diagnosis_date: Annotated[date | None, Field(examples=["2024-05-12"], default=None)]
    notes: Annotated[str | None, Field(max_length=2000, examples=["Updated notes"], default=None)]

    @field_validator("condition_name", "notes", mode="before")
    @classmethod
    def normalize_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("severity", "condition_status", mode="before")
    @classmethod
    def normalize_enum_fields(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("diagnosis_date")
    @classmethod
    def validate_diagnosis_date(cls, v: date | None):
        if v is not None and v > date.today():
            raise ValueError("diagnosis_date cannot be in the future")
        return v
