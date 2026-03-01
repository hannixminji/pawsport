from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..core.enums import MedicationAdministrationRoute, MedicationFrequency, MedicationStatus
from ..core.schemas import PersistentDeletion, TimestampSchema


class PetMedicationBase(BaseModel):
    medication_name: Annotated[str, Field(min_length=3, max_length=255, examples=["Amoxicillin"])]
    dosage: Annotated[str, Field(min_length=1, max_length=100, examples=["250 mg"])]
    administration_route: Annotated[MedicationAdministrationRoute, Field(examples=[MedicationAdministrationRoute.ORAL])]
    frequency: Annotated[MedicationFrequency, Field(examples=[MedicationFrequency.ONCE_DAILY])]
    start_date: Annotated[date, Field(examples=["2026-01-20"])]
    medication_status: Annotated[MedicationStatus, Field(examples=[MedicationStatus.ACTIVE])]
    end_date: Annotated[date | None, Field(examples=["2026-01-27"], default=None)]
    notes: Annotated[str | None, Field(max_length=2000, examples=["Take with food"], default=None)]

    @field_validator("medication_name", "dosage", mode="before")
    @classmethod
    def normalize_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("administration_route", "frequency", "medication_status", mode="before")
    @classmethod
    def normalize_enum_fields(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @model_validator(mode="after")
    def validate_end_date_after_start_date(self):
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must be the same as or after start_date")
        return self

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class PetMedication(TimestampSchema, PetMedicationBase, PersistentDeletion):
    pet_id: int


class PetMedicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pet_id: int
    medication_name: str
    dosage: str
    administration_route: MedicationAdministrationRoute
    frequency: MedicationFrequency
    start_date: date
    medication_status: MedicationStatus
    created_at: datetime
    end_date: date | None
    notes: str | None


class PetMedicationCreate(PetMedicationBase):
    model_config = ConfigDict(extra="forbid")


class PetMedicationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medication_name: Annotated[str | None, Field(min_length=3, max_length=255, examples=["Amoxicillin"], default=None)]
    dosage: Annotated[str | None, Field(min_length=1, max_length=100, examples=["250 mg"], default=None)]
    administration_route: Annotated[
        MedicationAdministrationRoute | None,
        Field(
            examples=[MedicationAdministrationRoute.ORAL],
            default=None,
        ),
    ]
    frequency: Annotated[MedicationFrequency | None, Field(examples=[MedicationFrequency.ONCE_DAILY], default=None)]
    start_date: Annotated[date | None, Field(examples=["2026-01-20"], default=None)]
    medication_status: Annotated[MedicationStatus | None, Field(examples=[MedicationStatus.ACTIVE], default=None)]
    end_date: Annotated[date | None, Field(examples=["2026-01-27"], default=None)]
    notes: Annotated[str | None, Field(max_length=2000, examples=["Updated notes"], default=None)]

    @field_validator("medication_name", "dosage", "notes", mode="before")
    @classmethod
    def normalize_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("administration_route", "frequency", "medication_status", mode="before")
    @classmethod
    def normalize_enum_fields(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @model_validator(mode="after")
    def validate_end_date_after_start_date(self):
        if self.start_date is not None and self.end_date is not None:
            if self.end_date < self.start_date:
                raise ValueError("end_date must be the same as or after start_date")
        return self
