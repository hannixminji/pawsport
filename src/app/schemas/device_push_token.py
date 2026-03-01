from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.enums import PushTokenPlatform, PushTokenProvider
from ..core.schemas import TimestampSchema


class DevicePushTokenBase(BaseModel):
    provider: Annotated[PushTokenProvider, Field(examples=[PushTokenProvider.FCM])]
    platform: Annotated[PushTokenPlatform, Field(examples=[PushTokenPlatform.ANDROID])]
    token: Annotated[str, Field(min_length=10, max_length=512, examples=["fcm_token_here"])]

    @field_validator("provider", "platform", mode="before")
    @classmethod
    def normalize_enum_fields(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("token", mode="before")
    @classmethod
    def normalize_token(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class DevicePushToken(TimestampSchema, DevicePushTokenBase):
    mobile_user_id: int


class DevicePushTokenUpsert(DevicePushTokenBase):
    model_config = ConfigDict(extra="forbid")
