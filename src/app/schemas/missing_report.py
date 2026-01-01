from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_extra_types.phone_numbers import PhoneNumber

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema
from .pet import PetReadWithPrimaryProfilePicture


class MissingReportStatus(str):
    MISSING = "missing"
    FOUND = "found"
    RETURNED = "returned"
    CLOSED = "closed"


class GeoPoint(BaseModel):
    latitude: Annotated[float, Field(ge=-90, le=90, examples=[37.7749])]
    longitude: Annotated[float, Field(ge=-180, le=180, examples=[-122.4194])]


class MapViewport(BaseModel):
    north: Annotated[float, Field(ge=-90, le=90, examples=[37.423])]
    south: Annotated[float, Field(ge=-90, le=90, examples=[37.419])]
    east: Annotated[float, Field(ge=-180, le=180, examples=[-122.082])]
    west: Annotated[float, Field(ge=-180, le=180, examples=[-122.087])]
    user_latitude: Annotated[float | None, Field(default=None, ge=-90, le=90, examples=[37.4219999])]
    user_longitude: Annotated[float | None, Field(default=None, ge=-180, le=180, examples=[-122.0840575])]


class MissingReportBase(BaseModel):
    last_seen_location: GeoPoint
    last_seen_address: Annotated[str, Field(min_length=3, max_length=512)]
    last_seen_datetime: datetime
    contact_name: Annotated[str, Field(min_length=2, max_length=30)]
    contact_number: Annotated[str, Field(min_length=5, max_length=20)]
    contact_address: Annotated[str | None, Field(default=None, max_length=512)]
    description: Annotated[str | None, Field(default=None, max_length=2000)]
    status: Annotated[
        str,
        Field(
            pattern=r"^(?i)(missing|found|returned|closed)$",
            default=MissingReportStatus.MISSING,
            examples=["missing", "found", "returned", "closed"],
        ),
    ]

    @field_validator("status")
    @classmethod
    def normalize_status(cls, v):
        if not v:
            return v
        return v.lower()


class MissingReport(TimestampSchema, MissingReportBase, UUIDSchema, PersistentDeletion):
    id: int
    pet_id: Annotated[int, Field(..., ge=1)]


class MissingReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pet: PetReadWithPrimaryProfilePicture
    location: dict[str, float]
    last_seen_address: str
    last_seen_datetime: datetime
    contact_name: str
    contact_number: str
    contact_address: str | None
    description: str | None
    status: str


class MissingReportCreate(MissingReportBase):
    model_config = ConfigDict(extra="forbid")


class MissingReportUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_seen_location: GeoPoint | None = None
    last_seen_address: Annotated[str | None, Field(default=None, max_length=512)]
    last_seen_datetime: Annotated[datetime | None, Field(default=None)]
    contact_name: Annotated[str | None, Field(default=None, max_length=30)]
    contact_number: Annotated[PhoneNumber | None, Field(default=None)]
    contact_address: Annotated[str | None, Field(default=None, max_length=512)]
    description: Annotated[str | None, Field(default=None, max_length=2000)]
    status: Annotated[
        str | None,
        Field(
            default=None,
            pattern=r"^(?i)(missing|found|returned|closed)$",
            examples=["missing", "found", "returned", "closed"],
        ),
    ]

    @field_validator("status")
    @classmethod
    def normalize_status(cls, v):
        if not v:
            return v
        return v.lower()


class MissingReportUpdateInternal(MissingReportUpdate):
    updated_at: datetime


class MissingReportDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime
