from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.schemas import TimestampSchema


class NotificationFeature(str, Enum):
    NEARBY_REPORT_ALERTS = "nearby_report_alerts"


class NotificationPreferenceBase(BaseModel):
    feature: Annotated[NotificationFeature, Field(examples=[NotificationFeature.NEARBY_REPORT_ALERTS])]
    is_enabled: Annotated[bool, Field(examples=[False], default=False)]

    @field_validator("feature", mode="before")
    @classmethod
    def normalize_feature(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v


class NotificationPreference(TimestampSchema, NotificationPreferenceBase):
    user_id: int


class NotificationPreferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    feature: str
    is_enabled: bool


class NotificationPreferenceCreate(NotificationPreferenceBase):
    model_config = ConfigDict(extra="forbid")


class NotificationPreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_enabled: Annotated[bool | None, Field(examples=[True], default=None)]
