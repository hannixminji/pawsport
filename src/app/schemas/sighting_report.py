from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema
from .sighting_report_image import SightingReportImageCreate, SightingReportImageRead


class GeoPoint(BaseModel):
    latitude: Annotated[float, Field(ge=-90, le=90, examples=[37.7749])]
    longitude: Annotated[float, Field(ge=-180, le=180, examples=[-122.4194])]


class SightingReportBase(BaseModel):
    pet_type: Annotated[str, Field(pattern=r"^(?i)(cat|dog)$", examples=["cat", "dog"])]
    sighted_at_datetime: datetime
    sighting_location: GeoPoint
    address: Annotated[str, Field(min_length=3, max_length=512)]
    description: Annotated[str | None, Field(default=None, max_length=2000)]

    @field_validator("pet_type")
    @classmethod
    def normalize_pet_type(cls, v):
        if not v:
            return v
        return v.lower()


class SightingReport(TimestampSchema, SightingReportBase, UUIDSchema, PersistentDeletion):
    user_id: int


class SightingReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    pet_type: str
    sighted_at_datetime: datetime
    location: GeoPoint
    address: str
    description: str | None
    images: list[SightingReportImageRead]


class SightingReportWithMatches(SightingReportRead):
    matches: list[dict] | None = None


class SightingReportCreate(SightingReportBase):
    model_config = ConfigDict(extra="forbid")


class SightingReportCreateInternal(SightingReportCreate):
    user_id: int


class SightingReportCreateWithImages(SightingReportCreate):
    images: Annotated[list[SightingReportImageCreate], Field(..., min_length=1, max_length=10)]

    @field_validator("images", mode="after")
    @classmethod
    def validate_images_sort_order(cls, images):
        if not images:
            return images

        sort_orders = [image.sort_order for image in images]

        if len(sort_orders) != len(set(sort_orders)):
            raise ValueError("Image order numbers must not have duplicates")

        return images


class SightingReportUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sighted_at_datetime: Annotated[datetime | None, Field(default=None)]
    description: Annotated[str | None, Field(default=None, max_length=2000)]


class SightingReportImageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[int | None, Field(default=None)]
    image_object_key: Annotated[
        str | None, Field(min_length=1, max_length=1024, examples=["path/to/image.jpg"], default=None)
    ]
    sort_order: Annotated[int, Field(ge=0, le=9, examples=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9])]


class SightingReportUpdateWithImages(SightingReportUpdate):
    images: Annotated[list[SightingReportImageUpdate], Field(..., min_length=1, max_length=10)]

    @field_validator("images", mode="after")
    @classmethod
    def validate_images_sort_order(cls, images):
        if not images:
            return images

        sort_orders = [image.sort_order for image in images]

        if len(sort_orders) != len(set(sort_orders)):
            raise ValueError("Image order numbers must not have duplicates")

        return images


class SightingReportUpdateInternal(SightingReportUpdate):
    updated_at: datetime


class SightingReportDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime
