from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.schemas import TimestampSchema


class TierBase(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=50, examples=["free"])]

    @field_validator("name", mode="before")
    def normalize_name(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class Tier(TimestampSchema, TierBase):
    pass


class TierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime


class TierCreate(TierBase):
    model_config = ConfigDict(extra="forbid")


class TierUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str | None, Field(min_length=1, max_length=50, examples=["premium"], default=None)]

    @field_validator("name", mode="before")
    def normalize_name(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class TierBulkDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: Annotated[set[int], Field(min_length=1, max_length=100)]

    @field_validator("ids", mode="before")
    @classmethod
    def validate_ids(cls, v):
        if not isinstance(v, list):
            raise ValueError("ids must be a list")

        if len(v) != len(set(v)):
            raise ValueError("ids must not contain duplicates")

        if any(id_ < 1 for id_ in v):
            raise ValueError("each id must be >= 1")

        return v
