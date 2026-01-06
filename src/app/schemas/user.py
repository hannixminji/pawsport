from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic_extra_types.phone_numbers import PhoneNumber

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema


class UserBase(BaseModel):
    first_name: Annotated[str, Field(min_length=2, max_length=30, examples=["John"])]
    last_name: Annotated[str, Field(min_length=2, max_length=30, examples=["Doe"])]
    username: Annotated[str, Field(min_length=3, max_length=20, pattern=r"^[a-z0-9]+$", examples=["userson"])]
    email: Annotated[EmailStr, Field(examples=["user.userson@example.com"])]
    phone_number: Annotated[PhoneNumber, Field(examples=["+639123456789"])]
    profile_image_object_key: Annotated[
        str | None, Field(min_length=1, max_length=1024, examples=["path/to/image.jpg"], default=None)
    ]
    country: Annotated[str | None, Field(max_length=60, examples=["Philippines"], default=None)]
    street_address_1: Annotated[str | None, Field(max_length=255, examples=["123 Main St"], default=None)]
    street_address_2: Annotated[str | None, Field(max_length=255, examples=["Apt 5B"], default=None)]
    city: Annotated[str | None, Field(max_length=100, examples=["Caloocan"], default=None)]
    state_province_region: Annotated[str | None, Field(max_length=100, examples=["Metro Manila"], default=None)]
    postal_code: Annotated[str | None, Field(max_length=16, examples=["1400"], default=None)]


class User(TimestampSchema, UserBase, UUIDSchema, PersistentDeletion):
    hashed_password: str | None = None
    is_superuser: bool = False
    tier_id: int | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str
    username: str
    email: EmailStr
    phone_number: str | None
    tier_id: int | None
    profile_image_url: str | None
    country: str | None
    street_address_1: str | None
    street_address_2: str | None
    city: str | None
    state_province_region: str | None
    postal_code: str | None


class UserCreate(UserBase):
    model_config = ConfigDict(extra="forbid")

    password: Annotated[
        str | None,
        Field(pattern=r"^.{8,}|[0-9]+|[A-Z]+|[a-z]+|[^a-zA-Z0-9]+$", examples=["Str1ngst!"], default=None)
    ]


class UserCreateInternal(UserBase):
    hashed_password: str | None = None


class UserSignup(BaseModel):
    username: Annotated[str, Field(min_length=3, max_length=20, pattern=r"^[a-z0-9]+$", examples=["userson"])]
    email: Annotated[EmailStr, Field(examples=["user.userson@example.com"])]


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
