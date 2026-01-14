from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema


class PetProfileImageBase(BaseModel):
    image_object_key: Annotated[str, Field(min_length=1, max_length=1024, examples=["path/to/image.jpg"])]
    sort_order: Annotated[int, Field(ge=0, le=4, examples=[0, 1, 2, 3, 4])]
    is_primary: Annotated[bool, Field(examples=[True, False], default=False)]


class PetProfileImage(TimestampSchema, PetProfileImageBase, UUIDSchema, PersistentDeletion):
    pet_id: int


class PetProfileImageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pet_id: int
    image_url: str
    sort_order: int
    is_primary: bool


class PetProfileImageCreate(PetProfileImageBase):
    model_config = ConfigDict(extra="forbid")


class PetProfileImageCreateInternal(PetProfileImageCreate):
    pet_id: int


class PetProfileImageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_object_key: Annotated[
        str | None, Field(min_length=1, max_length=1024, examples=["path/to/image.jpg"], default=None)
    ]
    sort_order: Annotated[int | None, Field(ge=0, le=4, examples=[0, 1, 2, 3, 4], default=None)]
    is_primary: Annotated[bool | None, Field(examples=[True, False], default=None)]


class PetProfileImageUpdateInternal(PetProfileImageUpdate):
    updated_at: datetime


class PetProfileImageDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime
