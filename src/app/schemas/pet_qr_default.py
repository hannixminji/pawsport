from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ..core.schemas import TimestampSchema


class PetQRDefaultBase(BaseModel):
    show_owner_name: Annotated[bool, Field(default=False, examples=[False])]
    show_email: Annotated[bool, Field(default=False, examples=[False])]
    show_phone_number: Annotated[bool, Field(default=False, examples=[False])]
    show_address: Annotated[bool, Field(default=False, examples=[False])]


class PetQRDefault(TimestampSchema, PetQRDefaultBase):
    owner_id: int


class PetQRDefaultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    show_owner_name: bool
    show_email: bool
    show_phone_number: bool
    show_address: bool
    owner_id: int | None


class PetQRDefaultUpsert(PetQRDefaultBase):
    model_config = ConfigDict(extra="forbid")
