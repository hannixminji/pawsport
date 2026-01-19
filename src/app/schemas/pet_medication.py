from datetime import date, datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema


class MedicationFrequency(str, Enum):
    ONCE_DAILY = "once_daily"
    TWICE_DAILY = "twice_daily"
    THREE_TIMES_DAILY = "three_times_daily"
    EVERY_OTHER_DAY = "every_other_day"
    WEEKLY = "weekly"
    AS_NEEDED = "as_needed"


class MedicationRoute(str, Enum):
    ORAL = "oral"
    TOPICAL = "topical"
    INJECTION = "injection"
    INHALATION = "inhalation"
    OCULAR = "ocular"
    OTIC = "otic"
    OTHER = "other"


class PetMedicationBase(BaseModel):
    medication: Annotated[str, Field(min_length=3, max_length=255, examples=["Amoxicillin"])]
    dosage: Annotated[str, Field(min_length=1, max_length=100, examples=["250 mg"])]
    frequency: Annotated[MedicationFrequency, Field(examples=[MedicationFrequency.ONCE_DAILY])]
    route: Annotated[MedicationRoute, Field(examples=[MedicationRoute.ORAL])]
    start_date: Annotated[date, Field(examples=["2026-01-20"])]
    end_date: Annotated[date | None, Field(examples=["2026-01-27"], default=None)]

    @field_validator("medication", "dosage")
    @classmethod
    def normalize_text_fields(cls, v: str) -> str:
        return v.strip()

    @field_validator("end_date")
    @classmethod
    def validate_end_after_start(cls, end_date: date | None, info):
        start_date = info.data.get("start_date")
        if end_date is None or start_date is None:
            return end_date
        if end_date < start_date:
            raise ValueError("End date must be the same as or after start date")
        return end_date


class PetMedication(TimestampSchema, PetMedicationBase, UUIDSchema, PersistentDeletion):
    pet_id: int


class PetMedicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pet_id: int
    medication: str
    dosage: str
    frequency: MedicationFrequency
    route: MedicationRoute
    start_date: date
    end_date: date | None


class PetMedicationCreate(PetMedicationBase):
    model_config = ConfigDict(extra="forbid")


class PetMedicationCreateInternal(PetMedicationCreate):
    pet_id: int


class PetMedicationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medication: Annotated[str | None, Field(min_length=3, max_length=255, examples=["Amoxicillin"], default=None)]
    dosage: Annotated[str | None, Field(min_length=1, max_length=100, examples=["250 mg"], default=None)]
    frequency: Annotated[MedicationFrequency | None, Field(examples=[MedicationFrequency.ONCE_DAILY], default=None)]
    route: Annotated[MedicationRoute | None, Field(examples=[MedicationRoute.ORAL], default=None)]
    start_date: Annotated[date | None, Field(examples=["2026-01-20"], default=None)]
    end_date: Annotated[date | None, Field(examples=["2026-01-27"], default=None)]

    @field_validator("medication", "dosage")
    @classmethod
    def normalize_text_fields(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v


class PetMedicationUpdateInternal(PetMedicationUpdate):
    updated_at: datetime


class PetMedicationDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime
