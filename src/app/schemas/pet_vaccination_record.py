from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema


class PetVaccinationRecordBase(BaseModel):
    file_object_key: Annotated[str, Field(min_length=1, max_length=1024, examples=["path/to/vaccine.pdf"])]
    expiry_date: date


class PetVaccinationRecord(TimestampSchema, PetVaccinationRecordBase, UUIDSchema, PersistentDeletion):
    pet_id: int


class PetVaccinationRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pet_id: int
    file_url: str
    expiry_date: date


class PetVaccinationRecordCreate(PetVaccinationRecordBase):
    model_config = ConfigDict(extra="forbid")


class PetVaccinationRecordCreateInternal(PetVaccinationRecordCreate):
    pet_id: int


class PetVaccinationRecordUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_object_key: Annotated[
        str | None,
        Field(min_length=1, max_length=1024, examples=["path/to/vaccine.pdf"], default=None)
    ]
    expiry_date: Annotated[date | None, Field(default=None)]


class PetVaccinationRecordUpdateInternal(PetVaccinationRecordUpdate):
    updated_at: datetime


class PetVaccinationRecordDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime
