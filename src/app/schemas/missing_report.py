from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..core.enums import MissingReportStatus
from ..core.schemas import GeoPoint, PersistentDeletion, TimestampSchema
from .pet import PetReadWithPrimaryProfile


class MapViewport(BaseModel):
    north: Annotated[float, Field(ge=-90, le=90, examples=[37.423])]
    south: Annotated[float, Field(ge=-90, le=90, examples=[37.419])]
    east: Annotated[float, Field(ge=-180, le=180, examples=[-122.082])]
    west: Annotated[float, Field(ge=-180, le=180, examples=[-122.087])]
    user_latitude: Annotated[float | None, Field(default=None, ge=-90, le=90, examples=[37.4219999])]
    user_longitude: Annotated[float | None, Field(default=None, ge=-180, le=180, examples=[-122.0840575])]


class MissingReportBase(BaseModel):
    last_seen_at: Annotated[datetime, Field()]
    last_seen_location: Annotated[GeoPoint, Field()]
    last_seen_address: Annotated[str, Field(max_length=512)]
    description: Annotated[str | None, Field(max_length=2_000, default=None)]

    @field_validator("last_seen_address", mode="before")
    @classmethod
    def normalize_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("description", mode="before")
    @classmethod
    def normalize_optional_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v

    @field_validator("last_seen_at")
    @classmethod
    def validate_last_seen_at(cls, v: datetime):
        if v.tzinfo is None:
            raise ValueError("last_seen_at must include timezone info")
        if v > datetime.now(v.tzinfo):
            raise ValueError("last_seen_at cannot be in the future")
        return v

    @field_validator("last_seen_address")
    @classmethod
    def validate_no_control_characters_single_line(cls, v: str) -> str:
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


class MissingReport(TimestampSchema, MissingReportBase, PersistentDeletion):
    pet_id: int
    report_status: MissingReportStatus


class MissingReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pet: PetReadWithPrimaryProfile
    last_seen_at: datetime
    last_seen_location: dict[str, float] = Field(alias="last_seen_location_dict")
    last_seen_address: str
    report_status: MissingReportStatus
    created_at: datetime
    description: str | None


class MissingReportCreate(MissingReportBase):
    model_config = ConfigDict(extra="forbid")


class MissingReportUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_seen_at: Annotated[datetime | None, Field(default=None)]
    last_seen_location: Annotated[GeoPoint | None, Field(default=None)]
    last_seen_address: Annotated[str | None, Field(max_length=512, default=None)]
    description: Annotated[str | None, Field(max_length=2000, default=None)]

    @field_validator("last_seen_at")
    @classmethod
    def validate_last_seen_at(cls, v: datetime | None):
        if v is None:
            return None
        if v.tzinfo is None:
            raise ValueError("last_seen_at must include timezone info")
        if v > datetime.now(v.tzinfo):
            raise ValueError("last_seen_at cannot be in the future")
        return v

    @field_validator("last_seen_address", "description", mode="before")
    @classmethod
    def normalize_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v

    @model_validator(mode="before")
    @classmethod
    def validate_address_if_location_set(cls, values):
        last_seen_location = values.get("last_seen_location")
        last_seen_address = values.get("last_seen_address")
        if last_seen_location is not None and not last_seen_address:
            raise ValueError("last_seen_address must be set if last_seen_location is provided")

        return values

    @field_validator("last_seen_address")
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
