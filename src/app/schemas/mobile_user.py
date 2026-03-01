from datetime import datetime
from typing import Annotated

from fastapi import Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from pydantic_extra_types.phone_numbers import PhoneNumber

from ..core.enums import ActorType
from ..core.schemas import Actor, GeoPoint, PersistentDeletion, TimestampSchema
from ..core.security import get_ip


class MobileUserBase(BaseModel):
    username: Annotated[str, Field(min_length=3, max_length=20, pattern=r"^[a-z0-9]+$", examples=["userson"])]
    email: Annotated[EmailStr, Field(examples=["user.userson@example.com"])]
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

    @field_validator("username", "email", mode="before")
    @classmethod
    def normalize_username_and_email(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
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
    tier_id: int | None = None
    hashed_password: str | None = None
    nearby_report_alert_location: dict[str, float] | None = None
    last_active_at: datetime | None = None


class MobileUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    uuid: str
    created_at: datetime
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


class MobileActor(BaseModel):
    id: int
    tier_id: int
    actor_type: ActorType

    def to_actor(self, request: Request) -> Actor:
        return Actor(
            id=self.id,
            actor_type=self.actor_type,
            is_superuser=False,
            role_ids=None,
            request_id=getattr(request.state, "request_id", None),
            ip_address=get_ip(request),
            user_agent=request.headers.get("user-agent"),
        )


class MobileUserCreate(MobileUserBase):
    model_config = ConfigDict(extra="forbid")


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
    email: Annotated[EmailStr | None, Field(examples=["new@example.com"], default=None)]
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

    @field_validator("username", "email", mode="before")
    @classmethod
    def normalize_username_and_email(cls, v):
        if isinstance(v, str):
            stripped = v.strip().lower()
            return stripped if stripped else None
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


class MobileUserTierUpdate(BaseModel):
    tier_id: Annotated[int, Field(gt=0)]
