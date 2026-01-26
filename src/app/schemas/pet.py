import math
from datetime import date, datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema
from .pet_profile_image import PetProfileImageCreate, PetProfileImageRead


class PetType(str, Enum):
    CAT = "cat"
    DOG = "dog"

class PetSex(str, Enum):
    MALE = "male"
    FEMALE = "female"


class PetBase(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=25, examples=["Max"])]
    type: Annotated[PetType, Field(examples=[PetType.DOG])]
    breed: Annotated[str, Field(min_length=3, max_length=30, examples=["Golden Retriever"])]
    sex: Annotated[PetSex, Field(examples=[PetSex.MALE])]
    is_sterilized: Annotated[bool, Field(examples=[True, False])]
    date_of_birth: Annotated[date, Field(examples=["2020-06-15"])]
    weight_kg: Annotated[float | None, Field(gt=0, le=120, examples=[4.25], default=None)]
    color: Annotated[str | None, Field(min_length=1, max_length=30, examples=["black-white"], default=None)]
    markings: Annotated[str | None, Field(max_length=255, examples=["White patch on chest"], default=None)]

    @field_validator("name", "breed", mode="before")
    @classmethod
    def normalize_required_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("color", "markings", mode="before")
    @classmethod
    def normalize_optional_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v

    @field_validator("type", "sex", mode="before")
    @classmethod
    def normalize_enum_fields(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("color", "markings")
    @classmethod
    def validate_printable_optional_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if any(ch for ch in v if not ch.isprintable()):
            raise ValueError("text fields must not contain control characters")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("date_of_birth must not be in the future")
        return v

    @field_validator("weight_kg")
    @classmethod
    def validate_weight_kg(cls, v: float | None) -> float | None:
        if v is None:
            return None
        if not math.isfinite(float(v)):
            raise ValueError("weight_kg must be a finite number")
        return float(v)


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
    is_sterilized: bool
    date_of_birth: date
    profile_images: list[PetProfileImageRead]
    weight_kg: float | None
    color: str | None
    markings: str | None
    qr_code_url: str | None


class PetReadWithPrimaryProfilePicture(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    name: str
    type: str
    breed: str
    sex: str
    is_sterilized: bool
    date_of_birth: date
    primary_profile_image_url: str
    weight_kg: float | None
    color: str | None
    markings: str | None
    qr_code_url: str | None


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
    type: Annotated[PetType | None, Field(examples=[PetType.DOG], default=None)]
    breed: Annotated[str | None, Field(min_length=3, max_length=30, examples=["Golden Retriever"], default=None)]
    sex: Annotated[PetSex | None, Field(examples=[PetSex.MALE], default=None)]
    is_sterilized: Annotated[bool | None, Field(examples=[True], default=None)]
    date_of_birth: Annotated[date | None, Field(examples=["2020-06-15"], default=None)]
    weight_kg: Annotated[float | None, Field(gt=0, le=120, examples=[4.25], default=None)]
    color: Annotated[str | None, Field(min_length=1, max_length=30, examples=["black-white"], default=None)]
    markings: Annotated[str | None, Field(max_length=255, examples=["White patch on chest"], default=None)]

    @field_validator("name", "breed", "color", "markings", mode="before")
    @classmethod
    def normalize_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v

    @field_validator("type", "sex", mode="before")
    @classmethod
    def normalize_enum_fields(cls, v):
        if isinstance(v, str):
            return v.strip().lower() or None
        return v

    @field_validator("name", "breed", "color", "markings")
    @classmethod
    def validate_printable_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if any(ch for ch in v if not ch.isprintable()):
            raise ValueError("text fields must not contain control characters")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, v: date | None) -> date | None:
        if v is None:
            return None

        if v > date.today():
            raise ValueError("date_of_birth must not be in the future")

        return v

    @field_validator("weight_kg")
    @classmethod
    def validate_weight_kg(cls, v: float | None) -> float | None:
        if v is None:
            return None
        if not math.isfinite(float(v)):
            raise ValueError("weight_kg must be a finite number")
        return float(v)


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
