from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.enums import PetSpecies
from ..core.schemas import PersistentDeletion, TimestampSchema
from .sighting_report_image import SightingReportImageCreate, SightingReportImageRead, SightingReportImageUpdate


class GeoPoint(BaseModel):
    latitude: Annotated[float, Field(ge=-90, le=90, examples=[37.7749])]
    longitude: Annotated[float, Field(ge=-180, le=180, examples=[-122.4194])]


class SightingReportBase(BaseModel):
    pet_species: Annotated[PetSpecies, Field(examples=[PetSpecies.DOG])]
    sighted_at: Annotated[datetime, Field()]
    sighting_location: Annotated[GeoPoint, Field()]
    sighting_address: Annotated[str, Field(max_length=512)]
    description: Annotated[str | None, Field(max_length=2000, default=None)]

    @field_validator("pet_species", mode="before")
    @classmethod
    def normalize_pet_species(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("sighted_at")
    @classmethod
    def validate_sighted_at(cls, v: datetime):
        if v.tzinfo is None:
            raise ValueError("sighted_at must include timezone info")
        if v > datetime.now(v.tzinfo):
            raise ValueError("sighted_at cannot be in the future")
        return v

    @field_validator("sighting_address", mode="before")
    @classmethod
    def normalize_sighting_address(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class SightingReport(TimestampSchema, SightingReportBase, PersistentDeletion):
    mobile_user_id: int | None = None


class SightingReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pet_species: PetSpecies
    sighted_at: datetime
    sighting_location: dict[str, float] = Field(alias="sighting_location_dict")
    sighting_address: str
    images: list[SightingReportImageRead]
    created_at: datetime
    mobile_user_id: int | None
    description: str | None


class SightingReportWithMatches(SightingReportRead):
    matches: list[dict] | None = None


class SightingReportCreate(SightingReportBase):
    model_config = ConfigDict(extra="forbid")


class SightingReportCreateWithImages(SightingReportCreate):
    images: Annotated[list[SightingReportImageCreate], Field(..., min_length=1, max_length=10)]

    @field_validator("images", mode="after")
    @classmethod
    def validate_images_sort_order(cls, images):
        if images is None:
            return images

        if not images:
            return images

        sort_orders = [image.sort_order for image in images]
        if len(sort_orders) != len(set(sort_orders)):
            raise ValueError("image sort_order must be unique")

        return images


class SightingReportUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sighted_at: Annotated[datetime | None, Field(default=None)]
    description: Annotated[str | None, Field(max_length=2000, default=None)]

    @field_validator("sighted_at")
    @classmethod
    def validate_sighted_at(cls, v: datetime | None):
        if v is None:
            return None
        if v.tzinfo is None:
            raise ValueError("sighted_at must include timezone info")
        if v > datetime.now(v.tzinfo):
            raise ValueError("sighted_at cannot be in the future")
        return v

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class SightingReportUpdateWithImages(SightingReportUpdate):
    images: Annotated[list[SightingReportImageUpdate], Field(..., min_length=1, max_length=10)]

    @field_validator("images", mode="after")
    @classmethod
    def validate_images_sort_order(cls, images):
        if images is None:
            return images

        if not images:
            return images

        sort_orders = [image.sort_order for image in images]
        if len(sort_orders) != len(set(sort_orders)):
            raise ValueError("image sort_order must be unique")

        return images
