import math
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, computed_field, field_validator

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema
from .pet_allergy import PetAllergyRead
from .pet_medical_condition import PetMedicalConditionRead
from .pet_profile_image import PetProfileImageCreate, PetProfileImageRead
from .pet_vaccination_record import PetVaccinationRecordRead


class PetType(StrEnum):
    CAT = "cat"
    DOG = "dog"


class PetSex(StrEnum):
    MALE = "male"
    FEMALE = "female"


class PetBase(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=25, examples=["Max"])]
    type: Annotated[PetType, Field(examples=[PetType.DOG])]
    breed: Annotated[str, Field(min_length=3, max_length=30, examples=["Golden Retriever"])]
    sex: Annotated[PetSex, Field(examples=[PetSex.MALE])]
    is_sterilized: Annotated[bool, Field(examples=[True, False])]
    date_of_birth: Annotated[date, Field(examples=["2020-06-15"])]
    qr_show_owner_name: Annotated[bool, Field(examples=[False], default=False)]
    qr_show_email: Annotated[bool, Field(examples=[False], default=False)]
    qr_show_phone_number: Annotated[bool, Field(examples=[True], default=False)]
    qr_show_address: Annotated[bool, Field(examples=[False], default=False)]
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
    qr_show_owner_name: bool
    qr_show_email: bool
    qr_show_phone_number: bool
    qr_show_address: bool
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


class OwnerQr(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    first_name: str | None
    last_name: str | None
    email: str | None
    phone_number: str | None
    street_address_1: str | None
    street_address_2: str | None
    city: str | None
    state_province_region: str | None
    postal_code: str | None
    country: str | None


class PetReadByQr(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    owner: OwnerQr = Field(exclude=True)
    id: int
    owner_id: int
    name: str
    type: str
    breed: str
    sex: str
    is_sterilized: bool
    date_of_birth: date
    qr_show_owner_name: bool
    qr_show_email: bool
    qr_show_phone_number: bool
    qr_show_address: bool
    profile_images: list[PetProfileImageRead]
    allergies: list[PetAllergyRead]
    medical_conditions: list[PetMedicalConditionRead]
    vaccination_records: list[PetVaccinationRecordRead]
    weight_kg: float | None
    color: str | None
    markings: str | None
    qr_code_url: str | None

    @computed_field(return_type=str | None)
    @property
    def owner_name(self) -> str | None:
        if not self.qr_show_owner_name:
            return None
        first = (self.owner.first_name or "").strip()
        last = (self.owner.last_name or "").strip()
        full = f"{first} {last}".strip()
        return full or None

    @computed_field(return_type=str | None)
    @property
    def owner_email(self) -> str | None:
        if not self.qr_show_email:
            return None
        return (self.owner.email or "").strip() or None

    @computed_field(return_type=str | None)
    @property
    def owner_phone_number(self) -> str | None:
        if not self.qr_show_phone_number:
            return None

        raw = (self.owner.phone_number or "").strip()
        if not raw:
            return None

        if raw.lower().startswith("tel:"):
            raw = raw[4:].strip()
        else:
            parsed = urlparse(raw)
            if parsed.scheme.lower() == "tel":
                raw = parsed.path.strip()

        return raw or None

    @computed_field(return_type=str | None)
    @property
    def owner_address(self) -> str | None:
        if not self.qr_show_address:
            return None

        parts: list[str] = []
        for val in (
            self.owner.street_address_1,
            self.owner.street_address_2,
            self.owner.city,
            self.owner.state_province_region,
            self.owner.postal_code,
            self.owner.country,
        ):
            if isinstance(val, str):
                val = val.strip()
            if val:
                parts.append(val)

        return ", ".join(parts) if parts else None

    @computed_field(return_type=str | None)
    @property
    def age(self) -> str | None:
        dob = self.date_of_birth
        if not dob:
            return None

        today = date.today()
        if dob > today:
            return None

        years = today.year - dob.year
        months = today.month - dob.month

        if today.day < dob.day:
            months -= 1

        if months < 0:
            years -= 1
            months += 12

        if years <= 0:
            return f"{months} month{'s' if months != 1 else ''}" if months else "0 months"
        if months == 0:
            return f"{years} year{'s' if years != 1 else ''}"
        return f"{years} year{'s' if years != 1 else ''} {months} month{'s' if months != 1 else ''}"


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
    qr_show_owner_name: Annotated[bool | None, Field(default=None, examples=[True])]
    qr_show_email: Annotated[bool | None, Field(default=None, examples=[True])]
    qr_show_phone_number: Annotated[bool | None, Field(default=None, examples=[False])]
    qr_show_address: Annotated[bool | None, Field(default=None, examples=[False])]

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
