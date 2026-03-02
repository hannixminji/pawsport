from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ..core.schemas import TimestampSchema


class NotificationPreferenceBase(BaseModel):
    nearby_report_alerts_enabled: Annotated[bool, Field(default=True, examples=[True])]
    pet_schedule_reminders_enabled: Annotated[bool, Field(default=True, examples=[True])]


class NotificationPreference(TimestampSchema, NotificationPreferenceBase):
    mobile_user_id: int


class NotificationPreferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nearby_report_alerts_enabled: bool
    pet_schedule_reminders_enabled: bool
    mobile_user_id: int | None


class NotificationPreferenceUpsert(NotificationPreferenceBase):
    model_config = ConfigDict(extra="forbid")
