from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema
from .pet_profile_image import PetProfileImageCreate, PetProfileImageRead


class PetBase(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=25, examples=["Max"])]
    type: Annotated[str, Field(pattern=r"^(?i)(cat|dog)$", examples=["Cat", "Dog"])]
    breed: Annotated[str, Field(min_length=3, max_length=30, examples=["Golden Retriever"])]
    sex: Annotated[str, Field(pattern=r"^(?i)(male|female)$", examples=["Male", "Female"])]
    is_neutered: Annotated[bool, Field(examples=[True, False])]
    date_of_birth: Annotated[date, Field(examples=["2020-06-15"])]

    @field_validator("type", "sex")
    @classmethod
    def normalize_fields(cls, v):
        if not v:
            return v
        return v.lower()


class Pet(TimestampSchema, PetBase, UUIDSchema, PersistentDeletion):
    owner_id: int


class PetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    name: str
    type: str
    breed: str
    sex: str
    is_neutered: bool
    date_of_birth: date
    profile_images: list[PetProfileImageRead]


class PetReadWithPrimaryProfilePicture(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    name: str
    type: str
    breed: str
    sex: str
    is_neutered: bool
    date_of_birth: date
    primary_profile_image_url: str


class PetSearch(PetRead):
    score: float


class PetCreate(PetBase):
    model_config = ConfigDict(extra="forbid")


class PetCreateInternal(PetCreate):
    owner_id: int


class PetCreateWithProfileImages(PetCreate):
    profile_images: Annotated[list[PetProfileImageCreate], Field(..., min_length=1, max_length=5)]

    @field_validator("profile_images", mode="after")
    def check_exactly_one_primary(cls, profile_images):
        primary_count = sum(profile_image.is_primary for profile_image in profile_images)
        if primary_count != 1:
            raise ValidationError.from_exception_data(
                cls.__name__,
                [
                    {
                        "type": "value_error",
                        "loc": ("profile_images",),
                        "msg": "A pet must have exactly one primary profile image",
                        "input": profile_images,
                        "ctx": {"required_primary_count": 1, "error": ValueError()},
                    }
                ]
            )
        return profile_images


class PetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str | None, Field(min_length=2, max_length=25, examples=["Max"], default=None)]
    type: Annotated[str | None, Field(pattern=r"^(?i)(cat|dog)$", examples=["Cat", "Dog"], default=None)]
    breed: Annotated[str | None, Field(min_length=3, max_length=30, examples=["Golden Retriever"], default=None)]
    sex: Annotated[str | None, Field(pattern=r"^(?i)(male|female)$", examples=["Male", "Female"], default=None)]
    is_neutered: Annotated[bool | None, Field(examples=[True, False], default=None)]
    date_of_birth: Annotated[date | None, Field(examples=["2020-06-15"], default=None)]

    @field_validator("type", "sex")
    @classmethod
    def normalize_fields(cls, v):
        if not v:
            return v
        return v.capitalize()


class PetProfileImageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[int | None, Field(default=None)]
    image_url: Annotated[str | None, Field(default=None)]
    image_object_key: Annotated[
        str | None, Field(min_length=1, max_length=1024, examples=["path/to/image.jpg"], default=None)
    ]
    sort_order: Annotated[int, Field(ge=0, le=4, examples=[0, 1, 2, 3, 4])]
    is_primary: Annotated[bool, Field(examples=[True, False], default=False)]


class PetUpdateWithProfileImages(PetUpdate):
    profile_images: Annotated[list[PetProfileImageUpdate], Field(..., min_length=1, max_length=5)]


class PetUpdateInternal(PetUpdate):
    updated_at: datetime


class PetDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime
