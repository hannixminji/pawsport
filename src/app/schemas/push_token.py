from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.schemas import TimestampSchema


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

class PushToken(TimestampSchema, PushTokenBase):
    user_id: int
    last_seen_at: datetime


class PushTokenUpsert(PushTokenBase):
    model_config = ConfigDict(extra="forbid")
