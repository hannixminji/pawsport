from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_extra_types.phone_numbers import PhoneNumber

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema
from .pet import PetReadWithPrimaryProfilePicture


class MissingReportStatus(str, Enum):
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
    last_seen_location: Annotated[GeoPoint, Field()]
    last_seen_address: Annotated[str, Field(max_length=512)]
    last_seen_datetime: Annotated[datetime, Field()]
    contact_name: Annotated[str, Field(max_length=30)]
    contact_number: Annotated[PhoneNumber, Field()]
    contact_address: Annotated[str | None, Field(max_length=512, default=None)]
    description: Annotated[str | None, Field(max_length=2000, default=None)]
    status: Annotated[
        MissingReportStatus,
        Field(
            pattern=r"^(?i)(missing|found|returned|closed)$",
            examples=["missing", "found", "returned", "closed"],
        ),
    ]

    @field_validator("last_seen_address", "contact_name", "contact_number", mode="before")
    @classmethod
    def normalize_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("contact_address", "description", mode="before")
    @classmethod
    def normalize_optional_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v

    @field_validator("last_seen_address", "contact_name", "contact_address")
    @classmethod
    def validate_no_control_characters_single_line(cls, v: str | None) -> str | None:
        if v is None:
            return None

        if any(not ch.isprintable() for ch in v):
            raise ValueError("must not contain control characters")

        return v

    @field_validator("description")
    @classmethod
    def validate_no_control_characters_description(cls, v: str | None) -> str | None:
        if v is None:
            return None

        if any((not ch.isprintable()) and ch not in "\n\t" for ch in v):
            raise ValueError("description must not contain control characters")

        return v

    @field_validator("last_seen_datetime")
    @classmethod
    def validate_last_seen_datetime(cls, v: datetime):
        if v.tzinfo is None:
            raise ValueError("last_seen_datetime must include timezone info")

        if v > datetime.now(v.tzinfo):
            raise ValueError("last_seen_datetime cannot be in the future")

        return v

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v


class MissingReport(TimestampSchema, MissingReportBase, UUIDSchema, PersistentDeletion):
    id: int
    pet_id: int


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

    last_seen_location: Annotated[GeoPoint | None, Field(default=None)]
    last_seen_address: Annotated[str | None, Field(max_length=512, default=None)]
    last_seen_datetime: Annotated[datetime | None, Field(default=None)]
    contact_name: Annotated[str | None, Field(max_length=30, default=None)]
    contact_number: Annotated[PhoneNumber | None, Field(default=None)]
    contact_address: Annotated[str | None, Field(max_length=512, default=None)]
    description: Annotated[str | None, Field(max_length=2000, default=None)]
    status: Annotated[
        MissingReportStatus | None,
        Field(
            pattern=r"^(?i)(missing|found|returned|closed)$",
            examples=["missing", "found", "returned", "closed"],
            default=None,
        ),
    ]

    @field_validator(
        "last_seen_address",
        "contact_name",
        "contact_number",
        "contact_address",
        "description",
        mode="before",
    )
    @classmethod
    def normalize_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v

    @field_validator("last_seen_address", "contact_name", "contact_address")
    @classmethod
    def validate_no_control_characters_single_line(cls, v: str | None) -> str | None:
        if v is None:
            return None

        if any(not ch.isprintable() for ch in v):
            raise ValueError("must not contain control characters")

        return v

    @field_validator("description")
    @classmethod
    def validate_no_control_characters_description(cls, v: str | None) -> str | None:
        if v is None:
            return None

        if any((not ch.isprintable()) and ch not in "\n\t" for ch in v):
            raise ValueError("description must not contain control characters")

        return v

    @field_validator("last_seen_datetime")
    @classmethod
    def validate_last_seen_datetime(cls, v: datetime | None):
        if v is None:
            return None

        if v.tzinfo is None:
            raise ValueError("last_seen_datetime must include timezone info")

        if v > datetime.now(v.tzinfo):
            raise ValueError("last_seen_datetime cannot be in the future")

        return v

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, v):
        if isinstance(v, str):
            return v.strip().lower() or None
        return v


class MissingReportUpdateInternal(MissingReportUpdate):
    updated_at: datetime


class MissingReportDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime
