from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.schemas import PersistentDeletion, TimestampSchema


class AllergenType(str, Enum):
    FOOD = "food"
    MEDICATION = "medication"
    ENVIRONMENTAL = "environmental"
    OTHER = "other"


class AllergySeverity(str, Enum):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


class PetAllergyBase(BaseModel):
    allergen: Annotated[str, Field(min_length=3, max_length=255, examples=["Chicken"])]
    allergen_type: Annotated[AllergenType, Field(examples=[AllergenType.FOOD])]
    severity_level: Annotated[AllergySeverity, Field(examples=[AllergySeverity.MILD])]
    reaction: Annotated[
        str | None, Field(min_length=5, max_length=500, examples=["Itchy skin and watery eyes"], default=None)
    ]

    @field_validator("allergen", mode="before")
    @classmethod
    def normalize_allergen(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("reaction", mode="before")
    @classmethod
    def normalize_reaction(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v

    @field_validator("allergen_type", "severity_level", mode="before")
    @classmethod
    def normalize_enum_fields(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v


class PetAllergy(TimestampSchema, PetAllergyBase, PersistentDeletion):
    pet_id: int


class PetAllergyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pet_id: int
    allergen: str
    allergen_type: AllergenType
    severity_level: AllergySeverity
    reaction: str | None


class PetAllergyCreate(PetAllergyBase):
    model_config = ConfigDict(extra="forbid")


class PetAllergyCreateInternal(PetAllergyCreate):
    pet_id: int


class PetAllergyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allergen: Annotated[str | None, Field(min_length=3, max_length=255, examples=["Pollen"], default=None)]
    allergen_type: Annotated[AllergenType | None, Field(examples=[AllergenType.ENVIRONMENTAL], default=None)]
    severity_level: Annotated[AllergySeverity | None, Field(examples=[AllergySeverity.MODERATE], default=None)]
    reaction: Annotated[
        str | None, Field(min_length=5, max_length=500, examples=["Sneezing and itchy eyes"], default=None)
    ]

    @field_validator("allergen", "reaction", mode="before")
    @classmethod
    def normalize_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v

    @field_validator("allergen_type", "severity_level", mode="before")
    @classmethod
    def normalize_enum_fields(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v


class PetAllergyUpdateInternal(PetAllergyUpdate):
    updated_at: datetime


class PetAllergyDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime
