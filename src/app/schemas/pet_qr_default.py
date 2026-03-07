from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ..core.schemas import TimestampSchema


class PetQRDefaultBase(BaseModel):
    # Public Information
    show_owner_name: Annotated[bool, Field(default=False, examples=[False])]
    show_email: Annotated[bool, Field(default=False, examples=[False])]
    show_phone_number: Annotated[bool, Field(default=False, examples=[False])]
    show_address: Annotated[bool, Field(default=False, examples=[False])]

    # Pet Details
    show_pet_name: Annotated[bool, Field(default=True, examples=[True])]
    show_pet_breed: Annotated[bool, Field(default=True, examples=[True])]
    show_pet_age: Annotated[bool, Field(default=True, examples=[True])]
    show_pet_sex: Annotated[bool, Field(default=True, examples=[True])]
    show_pet_weight: Annotated[bool, Field(default=True, examples=[True])]
    show_pet_color: Annotated[bool, Field(default=True, examples=[True])]
    show_pet_markings: Annotated[bool, Field(default=True, examples=[True])]
    show_pet_sterilized: Annotated[bool, Field(default=True, examples=[True])]

    # Health Records
    show_medications: Annotated[bool, Field(default=False, examples=[False])]
    show_vaccines: Annotated[bool, Field(default=False, examples=[False])]
    show_allergies: Annotated[bool, Field(default=False, examples=[False])]


class PetQRDefault(TimestampSchema, PetQRDefaultBase):
    owner_id: int


class PetQRDefaultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    owner_id: int | None

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


class PetQRDefaultUpsert(PetQRDefaultBase):
    model_config = ConfigDict(extra="forbid")
