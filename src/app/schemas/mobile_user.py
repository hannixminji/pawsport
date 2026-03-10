import time
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, conint, field_validator
from pydantic_extra_types.phone_numbers import PhoneNumber

from ..core.enums import ActorType, AuthProvider, MobileUserAccountStatus
from ..core.schemas import Actor, GeoPoint, PersistentDeletion, StrongPassword, TimestampSchema
from ..core.utils.request import get_client_ip

PositiveInt = conint(gt=0)


class MobileUserBase(BaseModel):
    username: Annotated[str, Field(min_length=3, max_length=20, pattern=r"^[a-z0-9]+$", examples=["userson"])]
    first_name: Annotated[str | None, Field(min_length=2, max_length=30, examples=["John"], default=None)]
    last_name: Annotated[str | None, Field(min_length=2, max_length=30, examples=["Doe"], default=None)]
    phone_number: Annotated[PhoneNumber | None, Field(examples=["+639123456789"], default=None)]
    profile_image_object_key: Annotated[
        str | None,
        Field(
            min_length=1,
            max_length=1024,
            examples=["path/to/image.jpg"],
            default=None,
        ),
    ]
    country: Annotated[str | None, Field(max_length=60, examples=["Philippines"], default=None)]
    street_address_1: Annotated[str | None, Field(max_length=255, examples=["123 Main St"], default=None)]
    street_address_2: Annotated[str | None, Field(max_length=255, examples=["Apt 5B"], default=None)]
    city: Annotated[str | None, Field(max_length=100, examples=["Caloocan"], default=None)]
    state_province_region: Annotated[str | None, Field(max_length=100, examples=["Metro Manila"], default=None)]
    postal_code: Annotated[str | None, Field(max_length=16, examples=["1400"], default=None)]

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator(
        "first_name",
        "last_name",
        "country",
        "street_address_1",
        "street_address_2",
        "city",
        "state_province_region",
        mode="before"
    )
    @classmethod
    def normalize_optional_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("phone_number", mode="before")
    @classmethod
    def normalize_phone_number(cls, v):
        if isinstance(v, str):
            return v.strip()
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

    @field_validator("postal_code", mode="before")
    @classmethod
    def normalize_postal_code(cls, v):
        if isinstance(v, str):
            stripped = v.strip()
            if any(ch.isspace() for ch in stripped):
                raise ValueError("postal_code must not contain whitespace")
            return stripped
        return v

    @field_validator("country", "street_address_1", "street_address_2", "city", "state_province_region", "postal_code")
    @classmethod
    def validate_no_control_characters(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if any(not ch.isprintable() for ch in v):
            raise ValueError("must not contain control characters")
        return v


class MobileUser(TimestampSchema, MobileUserBase, PersistentDeletion):
    is_anonymous: bool
    is_email_verified: bool
    email: EmailStr | None
    tier_id: int | None = None
    hashed_password: str | None = None
    nearby_report_alert_location: dict[str, float] | None = None
    last_active_at: datetime | None = None


class MobileUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: UUID
    is_email_verified: bool
    created_at: datetime
    username: str | None
    email: EmailStr | None
    first_name: str | None
    last_name: str | None
    phone_number: str | None
    profile_image_url: str | None
    country: str | None
    street_address_1: str | None
    street_address_2: str | None
    city: str | None
    state_province_region: str | None
    postal_code: str | None
    nearby_report_alert_location: dict[str, float] | None = Field(alias="nearby_report_alert_location_dict")

    @field_validator("phone_number", mode="before")
    @classmethod
    def clean_phone_number(cls, v):
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


class MobileUserLinkedProvidersRead(BaseModel):
    auth_providers: list[AuthProvider]


class MobileActor(BaseModel):
    id: int
    tier_id: int | None
    actor_type: ActorType
    is_anonymous: bool = False

    def to_actor(self, request: Request) -> Actor:
        return Actor(
            id=self.id,
            actor_type=self.actor_type,
            is_superuser=False,
            is_anonymous=self.is_anonymous,
            role_ids=None,
            request_id=getattr(request.state, "request_id", None),
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            start_time=time.monotonic(),
        )


class MobileUserCreate(MobileUserBase):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[EmailStr, Field(examples=["user.userson@example.com"])]

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class MobileUserEmailPasswordRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[EmailStr, Field(examples=["user.userson@example.com"])]
    password: Annotated[StrongPassword, Field(examples=["Str1ngst!"])]

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class MobileUserEmailPasswordLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[EmailStr, Field(examples=["user.userson@example.com"])]
    password: Annotated[StrongPassword, Field(examples=["Str1ngst!"])]

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class MobileUserVerifyEmail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: Annotated[str, Field(min_length=43, max_length=43, examples=["abc123xyz..."])]


class MobileUserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: Annotated[
        str | None,
        Field(
            min_length=3,
            max_length=20,
            pattern=r"^[a-z0-9]+$",
            examples=["newname"],
            default=None,
        ),
    ]
    first_name: Annotated[str | None, Field(min_length=2, max_length=30, examples=["New"], default=None)]
    last_name: Annotated[str | None, Field(min_length=2, max_length=30, examples=["Name"], default=None)]
    phone_number: Annotated[PhoneNumber | None, Field(examples=["+639123456789"], default=None)]
    profile_image_object_key: Annotated[
        str | None,
        Field(
            min_length=1,
            max_length=1024,
            examples=["new/path.jpg"],
            default=None,
        ),
    ]
    country: Annotated[str | None, Field(max_length=60, examples=["Philippines"], default=None)]
    street_address_1: Annotated[str | None, Field(max_length=255, examples=["123 Main St"], default=None)]
    street_address_2: Annotated[str | None, Field(max_length=255, examples=["Apt 5B"], default=None)]
    city: Annotated[str | None, Field(max_length=100, examples=["Caloocan"], default=None)]
    state_province_region: Annotated[str | None, Field(max_length=100, examples=["Metro Manila"], default=None)]
    postal_code: Annotated[str | None, Field(max_length=16, examples=["1400"], default=None)]
    nearby_report_alert_location: Annotated[GeoPoint | None, Field(default=None)]

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("first_name", "last_name", mode="before")
    @classmethod
    def normalize_names(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("phone_number", mode="before")
    @classmethod
    def normalize_phone_number(cls, v):
        if isinstance(v, str):
            return v.strip()
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

    @field_validator("country", "street_address_1", "street_address_2", "city", "state_province_region", mode="before")
    @classmethod
    def normalize_optional_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("postal_code", mode="before")
    @classmethod
    def normalize_postal_code(cls, v):
        if isinstance(v, str):
            stripped = v.strip()
            if any(ch.isspace() for ch in stripped):
                raise ValueError("postal_code must not contain whitespace")
            return stripped
        return v

    @field_validator("country", "street_address_1", "street_address_2", "city", "state_province_region", "postal_code")
    @classmethod
    def validate_no_control_characters(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if any(not ch.isprintable() for ch in v):
            raise ValueError("must not contain control characters")
        return v


class MobileUserEmailChangeOtpVerify(BaseModel):
    model_config = ConfigDict(extra="forbid")

    otp: Annotated[str, Field(min_length=6, max_length=6, pattern=r"^\d{6}$", examples=["123456"])]


class MobileUserEmailChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_email: Annotated[EmailStr, Field(examples=["user.userson@example.com"])]
    current_password: Annotated[StrongPassword | None, Field(examples=["CurrentPass123!"], default=None)]

    @field_validator("new_email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class MobileUserTierUpdate(BaseModel):
    tier_id: Annotated[int, Field(gt=0)]


class MobileUserAccountStatusUpdate(BaseModel):
    account_status: MobileUserAccountStatus


class MobileUserBulkTierUpdate(BaseModel):
    user_ids: Annotated[set[int], Field(min_length=1, max_length=100)]
    tier_id: Annotated[int | None, Field(ge=1, default=None)]

    @field_validator("user_ids", mode="before")
    @classmethod
    def validate_ids(cls, v):
        if not isinstance(v, list):
            raise ValueError("user_ids must be a list")

        if len(v) != len(set(v)):
            raise ValueError("user_ids must not contain duplicates")

        if any(id_ < 1 for id_ in v):
            raise ValueError("each id must be >= 1")

        return v


class MobileUserPasswordUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: Annotated[StrongPassword, Field(examples=["CurrentPass123!"])]
    new_password: Annotated[StrongPassword, Field(examples=["NewPass456@"])]


class MobileUserForgotPassword(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[EmailStr, Field(examples=["user.userson@example.com"])]

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class MobileUserResetPassword(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: Annotated[str, Field(min_length=43, max_length=43, examples=["abc123xyz..."])]
    new_password: Annotated[StrongPassword, Field(examples=["NewPass456@"])]
