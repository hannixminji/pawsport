from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator
from pydantic_extra_types.phone_numbers import PhoneNumber

from app.core.security import get_ip

from ..core.enums import ActorType, AdminAccountStatus
from ..core.schemas import Actor, PersistentDeletion, TimestampSchema, UUIDSchema
from .schemas.admin_role import AdminRoleRead


class AdminUserBase(BaseModel):
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

    @field_validator("username", "email", mode="before")
    @classmethod
    def normalize_username_and_email(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
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


class AdminUser(TimestampSchema, AdminUserBase, UUIDSchema, PersistentDeletion):
    hashed_password: str
    account_status: AdminAccountStatus
    is_superuser: bool = False
    last_active_at: datetime | None = None


class AdminUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    uuid: UUID
    account_status: AdminAccountStatus
    is_superuser: bool
    created_at: datetime
    first_name: str | None
    last_name: str | None
    phone_number: str | None
    profile_image_url: str | None
    last_active_at: datetime | None

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


class AdminUserReadWithRoles(AdminUserRead):
    roles: list[AdminRoleRead]


class AdminUserLoginResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    is_superuser: bool
    profile_image_url: str | None = None


class AdminUserCreate(AdminUserBase):
    model_config = ConfigDict(extra="forbid")

    password: Annotated[SecretStr, Field(pattern=r"^.{8,}|[0-9]+|[A-Z]+|[a-z]+|[^a-zA-Z0-9]+$", examples=["Str1ngst!"])]


class AdminUserLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: Annotated[str, Field(min_length=3, max_length=20, pattern=r"^[a-z0-9]+$", examples=["admin"])]
    password: Annotated[str, Field(pattern=r"^.{8,}|[0-9]+|[A-Z]+|[a-z]+|[^a-zA-Z0-9]+$", examples=["Str1ngst!"])]


class AdminUserAssignRoles(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_ids: Annotated[set[int], Field(min_length=1, max_length=100)]

    @field_validator("role_ids", mode="before")
    @classmethod
    def validate_role_ids(cls, v):
        if not isinstance(v, list):
            raise ValueError("role_ids must be a list")

        if len(v) != len(set(v)):
            raise ValueError("role_ids must not contain duplicates")

        if any(role_id < 1 for role_id in v):
            raise ValueError("each role_id must be >= 1")

        return v


class AdminUserAssignPermissions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permission_ids: Annotated[set[int], Field(min_length=1, max_length=100)]

    @field_validator("permission_ids", mode="before")
    @classmethod
    def validate_permission_ids(cls, v):
        if not isinstance(v, list):
            raise ValueError("permission_ids must be a list")

        if len(v) != len(set(v)):
            raise ValueError("permission_ids must not contain duplicates")

        if any(permission_id < 1 for permission_id in v):
            raise ValueError("each permission_id must be >= 1")

        return v


class AdminUserUpdate(BaseModel):
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

    @field_validator("username", "email", mode="before")
    @classmethod
    def normalize_username_and_email(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
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


class AdminUserStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_status: Annotated[AdminAccountStatus, Field(examples=[AdminAccountStatus.SUSPENDED])]

    @field_validator("account_status", mode="before")
    @classmethod
    def normalize_account_status(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v


class AdminUserPasswordUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: Annotated[
        SecretStr,
        Field(
            pattern=r"^.{8,}|[0-9]+|[A-Z]+|[a-z]+|[^a-zA-Z0-9]+$",
            examples=["CurrentPass123!"],
        ),
    ]
    new_password: Annotated[
        SecretStr,
        Field(
            pattern=r"^.{8,}|[0-9]+|[A-Z]+|[a-z]+|[^a-zA-Z0-9]+$",
            examples=["NewPass456@"],
        ),
    ]


class AdminActor(BaseModel):
    id: int
    actor_type: ActorType
    is_superuser: bool
    role_ids: set[int] | None

    def to_actor(self, request: Request) -> Actor:
        return Actor(
            id=self.id,
            actor_type=self.actor_type,
            is_superuser=self.is_superuser,
            role_ids=list(self.role_ids) if self.role_ids else None,
            request_id=getattr(request.state, "request_id", None),
            ip_address=get_ip(request),
            user_agent=request.headers.get("user-agent"),
        )


class AdminUserBulkDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: Annotated[set[int], Field(min_length=1, max_length=100)]

    @field_validator("ids", mode="before")
    @classmethod
    def validate_ids(cls, v):
        if not isinstance(v, list):
            raise ValueError("ids must be a list")

        if len(v) != len(set(v)):
            raise ValueError("ids must not contain duplicates")

        if any(id_ < 1 for id_ in v):
            raise ValueError("each id must be >= 1")

        return v
