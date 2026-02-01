from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema


class PushPlatform(str, Enum):
    ANDROID = "android"
    IOS = "ios"


class PushTokenBase(BaseModel):
    token: Annotated[str, Field(min_length=10, max_length=512, examples=["fcm_token_here"])]
    platform: Annotated[PushPlatform, Field(examples=[PushPlatform.ANDROID])]

    @field_validator("token", mode="before")
    @classmethod
    def normalize_token(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("platform", mode="before")
    @classmethod
    def normalize_platform(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v


class PushToken(TimestampSchema, PushTokenBase, UUIDSchema, PersistentDeletion):
    user_id: int
    is_active: bool
    last_seen_at: datetime


class PushTokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    token: str
    platform: PushPlatform
    is_active: bool
    last_seen_at: datetime


class PushTokenCreate(PushTokenBase):
    model_config = ConfigDict(extra="forbid")


class PushTokenUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: Annotated[str | None, Field(min_length=10, max_length=512, default=None)]
    platform: Annotated[PushPlatform | None, Field(default=None)]
    is_active: Annotated[bool | None, Field(default=None)]
    last_seen_at: Annotated[datetime | None, Field(default=None)]

    @field_validator("token", mode="before")
    @classmethod
    def normalize_token(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v

    @field_validator("platform", mode="before")
    @classmethod
    def normalize_platform(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v
