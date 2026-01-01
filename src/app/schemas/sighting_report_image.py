from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema


class SightingReportImageBase(BaseModel):
    image_object_key: Annotated[str, Field(min_length=1, max_length=1024, examples=["path/to/image.jpg"])]
    sort_order: Annotated[int, Field(ge=0, le=9, examples=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9])]


class SightingReportImage(TimestampSchema, SightingReportImageBase, UUIDSchema, PersistentDeletion):
    sighting_report_id: int


class SightingReportImageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sighting_report_id: int
    image_url: str
    sort_order: int


class SightingReportImageCreate(SightingReportImageBase):
    model_config = ConfigDict(extra="forbid")


class SightingReportImageCreateInternal(SightingReportImageCreate):
    sighting_report_id: int


class SightingReportImageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_object_key: Annotated[
        str | None, Field(min_length=1, max_length=1024, examples=["path/to/image.jpg"], default=None)
    ]
    sort_order: Annotated[int | None, Field(ge=0, le=9, examples=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], default=None)]


class SightingReportImageUpdateInternal(SightingReportImageUpdate):
    updated_at: datetime


class SightingReportImageDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime
