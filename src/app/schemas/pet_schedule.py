from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema


class PetScheduleType(str, Enum):
    VET_VISIT = "vet_visit"
    VACCINATION = "vaccination"
    GROOMING = "grooming"
    FOOD = "food"
    WALK = "walk"
    MEDICINE = "medicine"
    PLAY_TIME = "play_time"
    OTHER = "other"


class PetScheduleBase(BaseModel):
    type: Annotated[PetScheduleType, Field(examples=[PetScheduleType.VET_VISIT])]
    title: Annotated[str, Field(min_length=3, max_length=255, examples=["Vet checkup"])]
    scheduled_at: Annotated[datetime, Field(examples=["2026-01-20T10:00:00+08:00"])]
    is_recurring: Annotated[bool, Field(examples=[True, False], default=False)]
    description: Annotated[str | None, Field(max_length=500, examples=["Annual checkup"], default=None)]
    recurrence_rule: Annotated[
        str | None, Field(min_length=1, max_length=1024, examples=["FREQ=WEEKLY;INTERVAL=1"], default=None)
    ]

    @field_validator("title", "description", "recurrence_rule")
    @classmethod
    def normalize_text_fields(cls, v):
        return v.strip() if isinstance(v, str) else v


class PetSchedule(TimestampSchema, PetScheduleBase, UUIDSchema, PersistentDeletion):
    pet_id: int


class PetScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pet_id: int
    type: PetScheduleType
    title: str
    scheduled_at: datetime
    is_recurring: bool
    description: str | None
    recurrence_rule: str | None
    next_scheduled_at: datetime | None


class PetScheduleCreate(PetScheduleBase):
    model_config = ConfigDict(extra="forbid")


class PetScheduleCreateInternal(PetScheduleCreate):
    pet_id: int


class PetScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Annotated[PetScheduleType | None, Field(examples=[PetScheduleType.VET_VISIT], default=None)]
    title: Annotated[str | None, Field(min_length=3, max_length=255, examples=["Vet checkup"], default=None)]
    scheduled_at: Annotated[datetime | None, Field(examples=["2026-01-20T10:00:00+08:00"], default=None)]
    description: Annotated[str | None, Field(max_length=500, examples=["Annual checkup"], default=None)]
    is_recurring: Annotated[bool | None, Field(examples=[True, False], default=None)]
    recurrence_rule: Annotated[
        str | None, Field(min_length=1, max_length=1024, examples=["FREQ=WEEKLY;INTERVAL=1"], default=None)
    ]

    @field_validator("title", "description", "recurrence_rule")
    @classmethod
    def normalize_text_fields(cls, v):
        return v.strip() if isinstance(v, str) else v


class PetScheduleUpdateInternal(PetScheduleUpdate):
    updated_at: datetime


class PetScheduleDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime
