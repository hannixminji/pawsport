from datetime import date, datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema


class MedicalConditionSeverity(str, Enum):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


class MedicalConditionStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    CHRONIC = "chronic"


class PetMedicalConditionBase(BaseModel):
    condition_name: Annotated[str, Field(min_length=3, max_length=255, examples=["Hip Dysplasia"])]
    severity_level: Annotated[MedicalConditionSeverity, Field(examples=[MedicalConditionSeverity.MODERATE])]
    condition_status: Annotated[MedicalConditionStatus, Field(examples=[MedicalConditionStatus.ACTIVE])]
    diagnosis_date: Annotated[date | None, Field(examples=["2024-05-12"], default=None)]

    @field_validator("condition_name")
    @classmethod
    def normalize_condition_name(cls, v: str) -> str:
        return v.strip()


class PetMedicalCondition(TimestampSchema, PetMedicalConditionBase, UUIDSchema, PersistentDeletion):
    pet_id: int


class PetMedicalConditionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pet_id: int
    condition_name: str
    severity_level: MedicalConditionSeverity
    condition_status: MedicalConditionStatus
    diagnosis_date: date | None


class PetMedicalConditionCreate(PetMedicalConditionBase):
    model_config = ConfigDict(extra="forbid")


class PetMedicalConditionCreateInternal(PetMedicalConditionCreate):
    pet_id: int


class PetMedicalConditionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condition_name: Annotated[str | None, Field(min_length=3, max_length=255, examples=["Hip Dysplasia"], default=None)]
    severity_level: Annotated[
        MedicalConditionSeverity | None, Field(examples=[MedicalConditionSeverity.MODERATE], default=None)
    ]
    condition_status: Annotated[
        MedicalConditionStatus | None, Field(examples=[MedicalConditionStatus.ACTIVE], default=None)
    ]
    diagnosis_date: Annotated[date | None, Field(examples=["2024-05-12"], default=None)]

    @field_validator("condition_name")
    @classmethod
    def normalize_condition_name(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v


class PetMedicalConditionUpdateInternal(PetMedicalConditionUpdate):
    updated_at: datetime


class PetMedicalConditionDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime
