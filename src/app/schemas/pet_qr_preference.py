from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ..core.schemas import TimestampSchema


class PetQRPreferenceBase(BaseModel):
    show_owner_name: Annotated[bool, Field(examples=[False], default=False)]
    show_email: Annotated[bool, Field(examples=[False], default=False)]
    show_phone_number: Annotated[bool, Field(examples=[False], default=False)]
    show_address: Annotated[bool, Field(examples=[False], default=False)]
    override_defaults: Annotated[bool, Field(examples=[False], default=False)]


class PetQRPreference(TimestampSchema, PetQRPreferenceBase):
    pet_id: int


class PetQRPreferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pet_id: int
    show_owner_name: bool
    show_email: bool
    show_phone_number: bool
    show_address: bool
    override_defaults: bool
    created_at: datetime


class PetQRPreferenceCreate(PetQRPreferenceBase):
    model_config = ConfigDict(extra="forbid")


class PetQRPreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    show_owner_name: Annotated[bool | None, Field(examples=[True], default=None)]
    show_email: Annotated[bool | None, Field(examples=[True], default=None)]
    show_phone_number: Annotated[bool | None, Field(examples=[True], default=None)]
    show_address: Annotated[bool | None, Field(examples=[True], default=None)]
    override_defaults: Annotated[bool | None, Field(examples=[True], default=None)]
