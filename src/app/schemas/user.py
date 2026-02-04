from datetime import datetime
from typing import Annotated, Any

from geoalchemy2.shape import to_shape
from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator
from pydantic_extra_types.phone_numbers import PhoneNumber

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema


class GeoPoint(BaseModel):
    latitude: Annotated[float, Field(ge=-90, le=90, examples=[37.7749])]
    longitude: Annotated[float, Field(ge=-180, le=180, examples=[-122.4194])]


class UserBase(BaseModel):
    username: Annotated[str, Field(min_length=3, max_length=20, pattern=r"^[a-z0-9]+$", examples=["userson"])]
    email: Annotated[EmailStr, Field(examples=["user.userson@example.com"])]
    phone_number: Annotated[PhoneNumber, Field(examples=["+639123456789"])]
    first_name: Annotated[str | None, Field(min_length=2, max_length=30, examples=["John"], default=None)]
    last_name: Annotated[str | None, Field(min_length=2, max_length=30, examples=["Doe"], default=None)]
    profile_image_object_key: Annotated[
        str | None, Field(min_length=1, max_length=1024, examples=["path/to/image.jpg"], default=None)
    ]
    country: Annotated[str | None, Field(max_length=60, examples=["Philippines"], default=None)]
    street_address_1: Annotated[str | None, Field(max_length=255, examples=["123 Main St"], default=None)]
    street_address_2: Annotated[str | None, Field(max_length=255, examples=["Apt 5B"], default=None)]
    city: Annotated[str | None, Field(max_length=100, examples=["Caloocan"], default=None)]
    state_province_region: Annotated[str | None, Field(max_length=100, examples=["Metro Manila"], default=None)]
    postal_code: Annotated[str | None, Field(max_length=16, examples=["1400"], default=None)]

    @field_validator(
        "first_name",
        "last_name",
        "country",
        "street_address_1",
        "street_address_2",
        "city",
        "state_province_region",
        "postal_code",
        mode="before"
    )
    @classmethod
    def normalize_optional_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v

    @field_validator("phone_number", mode="before")
    @classmethod
    def normalize_phone_number(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("profile_image_object_key")
    @classmethod
    def validate_profile_image_object_key(cls, v: str | None) -> str | None:
        if v is None:
            return None

        if any(ch.isspace() for ch in v):
            raise ValueError("profile_image_object_key must not contain whitespace")

        if "\\" in v or "'" in v or '"' in v:
            raise ValueError("profile_image_object_key must not contain backslashes or quotes")

        if any(ch for ch in v if not ch.isprintable()):
            raise ValueError("profile_image_object_key must not contain control characters")

        if v.startswith("/"):
            raise ValueError("profile_image_object_key must be a relative path")

        if "//" in v:
            raise ValueError("profile_image_object_key must not contain empty path segments")

        parts = v.split("/")
        if "." in parts or ".." in parts:
            raise ValueError("profile_image_object_key must not contain '.' or '..' path segments")

        if v.endswith("/"):
            raise ValueError("profile_image_object_key must not end with '/'")

        return v

    @field_validator("postal_code")
    @classmethod
    def validate_postal_code(cls, v: str | None) -> str | None:
        if v is None:
            return None

        if any(ch.isspace() for ch in v):
            raise ValueError("postal_code must not contain whitespace")

        return v


class User(TimestampSchema, UserBase, UUIDSchema, PersistentDeletion):
    hashed_password: str | None = None
    is_superuser: bool = False
    tier_id: int | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    first_name: str | None
    last_name: str | None
    phone_number: str | None
    tier_id: int | None
    profile_image_url: str | None
    country: str | None
    street_address_1: str | None
    street_address_2: str | None
    city: str | None
    state_province_region: str | None
    postal_code: str | None

    alert_center_geog: Any | None = Field(default=None, exclude=True)

    @field_validator("phone_number", mode="before")
    @classmethod
    def normalize_phone_number(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            if s.lower().startswith("tel:"):
                s = s[4:].strip()
            return s or None
        return v

    @computed_field
    @property
    def alert_center_latitude(self) -> float | None:
        if self.alert_center_geog is None:
            return None
        point = to_shape(self.alert_center_geog)
        return float(point.y)

    @computed_field
    @property
    def alert_center_longitude(self) -> float | None:
        if self.alert_center_geog is None:
            return None
        point = to_shape(self.alert_center_geog)
        return float(point.x)


class UserCreate(UserBase):
    model_config = ConfigDict(extra="forbid")

    password: Annotated[
        str | None,
        Field(pattern=r"^.{8,}|[0-9]+|[A-Z]+|[a-z]+|[^a-zA-Z0-9]+$", examples=["Str1ngst!"], default=None)
    ]


class UserCreateInternal(UserBase):
    hashed_password: str | None = None


class UserSignup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: Annotated[str, Field(min_length=3, max_length=20, pattern=r"^[a-z0-9]+$", examples=["userson"])]
    email: Annotated[EmailStr, Field(examples=["user.userson@example.com"])]

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: Annotated[str | None, Field(min_length=2, max_length=30, examples=["John"], default=None)]
    last_name: Annotated[str | None, Field(min_length=2, max_length=30, examples=["Doe"], default=None)]
    username: Annotated[
        str | None, Field(min_length=3, max_length=20, pattern=r"^[a-z0-9]+$", examples=["userberg"], default=None)
    ]
    email: Annotated[EmailStr | None, Field(examples=["user.userberg@example.com"], default=None)]
    phone_number: Annotated[PhoneNumber | None, Field(examples=["+639123456789"], default=None)]
    profile_image_object_key: Annotated[
        str | None, Field(min_length=1, max_length=1024, examples=["path/to/image.jpg"], default=None)
    ]
    country: Annotated[str | None, Field(max_length=60, default=None)]
    street_address_1: Annotated[str | None, Field(max_length=255, default=None)]
    street_address_2: Annotated[str | None, Field(max_length=255, default=None)]
    city: Annotated[str | None, Field(max_length=100, default=None)]
    state_province_region: Annotated[str | None, Field(max_length=100, default=None)]
    postal_code: Annotated[str | None, Field(max_length=16, default=None)]
    alert_center_geog: Annotated[GeoPoint | None, Field(default=None)]

    @field_validator(
        "first_name",
        "last_name",
        "phone_number",
        "country",
        "street_address_1",
        "street_address_2",
        "city",
        "state_province_region",
        "postal_code",
        mode="before"
    )
    @classmethod
    def normalize_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v

    @field_validator("username", "email", mode="before")
    @classmethod
    def normalize_username_and_email(cls, v):
        if isinstance(v, str):
            return v.strip().lower() or None
        return v

    @field_validator("profile_image_object_key")
    @classmethod
    def validate_profile_image_object_key(cls, v: str | None) -> str | None:
        if v is None:
            return None

        if any(ch.isspace() for ch in v):
            raise ValueError("profile_image_object_key must not contain whitespace")

        if "\\" in v or "'" in v or '"' in v:
            raise ValueError("profile_image_object_key must not contain backslashes or quotes")

        if any(ch for ch in v if not ch.isprintable()):
            raise ValueError("profile_image_object_key must not contain control characters")

        if v.startswith("/"):
            raise ValueError("profile_image_object_key must be a relative path")

        if "//" in v:
            raise ValueError("profile_image_object_key must not contain empty path segments")

        parts = v.split("/")
        if "." in parts or ".." in parts:
            raise ValueError("profile_image_object_key must not contain '.' or '..' path segments")

        if v.endswith("/"):
            raise ValueError("profile_image_object_key must not end with '/'")

        return v

    @field_validator("postal_code")
    @classmethod
    def validate_postal_code(cls, v: str | None) -> str | None:
        if v is None:
            return None

        if any(ch.isspace() for ch in v):
            raise ValueError("postal_code must not contain whitespace")

        return v


class UserUpdateInternal(UserUpdate):
    updated_at: datetime


class UserTierUpdate(BaseModel):
    tier_id: int


class UserDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime


class UserRestoreDeleted(BaseModel):
    is_deleted: bool
