from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ..core.schemas import TimestampSchema


class PetQRPreferenceBase(BaseModel):
    # Public Information
    show_owner_name: Annotated[bool, Field(examples=[False], default=False)]
    show_email: Annotated[bool, Field(examples=[False], default=False)]
    show_phone_number: Annotated[bool, Field(examples=[False], default=False)]
    show_address: Annotated[bool, Field(examples=[False], default=False)]

    # Pet Details
    show_pet_name: Annotated[bool, Field(examples=[True], default=True)]
    show_pet_breed: Annotated[bool, Field(examples=[True], default=True)]
    show_pet_age: Annotated[bool, Field(examples=[True], default=True)]
    show_pet_sex: Annotated[bool, Field(examples=[True], default=True)]
    show_pet_weight: Annotated[bool, Field(examples=[True], default=True)]
    show_pet_color: Annotated[bool, Field(examples=[True], default=True)]
    show_pet_markings: Annotated[bool, Field(examples=[True], default=True)]
    show_pet_sterilized: Annotated[bool, Field(examples=[True], default=True)]

    # Health Records
    show_medications: Annotated[bool, Field(examples=[False], default=False)]
    show_vaccines: Annotated[bool, Field(examples=[False], default=False)]
    show_allergies: Annotated[bool, Field(examples=[False], default=False)]

    override_defaults: Annotated[bool, Field(examples=[False], default=False)]


class PetQRPreference(TimestampSchema, PetQRPreferenceBase):
    pet_id: int


class PetQRPreferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pet_id: int

    # Public Information
    show_owner_name: bool
    show_email: bool
    show_phone_number: bool
    show_address: bool

    # Pet Details
    show_pet_name: bool
    show_pet_breed: bool
    show_pet_age: bool
    show_pet_sex: bool
    show_pet_weight: bool
    show_pet_color: bool
    show_pet_markings: bool
    show_pet_sterilized: bool

    # Health Records
    show_medications: bool
    show_vaccines: bool
    show_allergies: bool

    override_defaults: bool
    created_at: datetime


class PetQRPreferenceCreate(PetQRPreferenceBase):
    model_config = ConfigDict(extra="forbid")


class PetQRPreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Public Information
    show_owner_name: Annotated[bool | None, Field(examples=[True], default=None)]
    show_email: Annotated[bool | None, Field(examples=[True], default=None)]
    show_phone_number: Annotated[bool | None, Field(examples=[True], default=None)]
    show_address: Annotated[bool | None, Field(examples=[True], default=None)]

    # Pet Details
    show_pet_name: Annotated[bool | None, Field(examples=[True], default=None)]
    show_pet_breed: Annotated[bool | None, Field(examples=[True], default=None)]
    show_pet_age: Annotated[bool | None, Field(examples=[True], default=None)]
    show_pet_sex: Annotated[bool | None, Field(examples=[True], default=None)]
    show_pet_weight: Annotated[bool | None, Field(examples=[True], default=None)]
    show_pet_color: Annotated[bool | None, Field(examples=[True], default=None)]
    show_pet_markings: Annotated[bool | None, Field(examples=[True], default=None)]
    show_pet_sterilized: Annotated[bool | None, Field(examples=[True], default=None)]

    # Health Records
    show_medications: Annotated[bool | None, Field(examples=[True], default=None)]
    show_vaccines: Annotated[bool | None, Field(examples=[True], default=None)]
    show_allergies: Annotated[bool | None, Field(examples=[True], default=None)]

    override_defaults: Annotated[bool | None, Field(examples=[True], default=None)]
