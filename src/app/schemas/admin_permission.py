from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.schemas import TimestampSchema


class AdminPermissionBase(BaseModel):
    key: Annotated[str, Field(min_length=3, max_length=100, examples=["create:post"])]
    name: Annotated[str, Field(min_length=3, max_length=100, examples=["Create Post"])]
    description: Annotated[str | None, Field(max_length=1_000, examples=["Allows creating new posts"], default=None)]

    @field_validator("key", "name", mode="before")
    @classmethod
    def normalize_key_and_name(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("key")
    @classmethod
    def validate_key_format(cls, v: str) -> str:
        if not v.islower():
            raise ValueError("key must be lowercase")
        if any(ch.isspace() for ch in v):
            raise ValueError("key must not contain whitespace")
        allowed_chars = set("abcdefghijklmnopqrstuvwxyz0123456789_:")
        if not all(ch in allowed_chars for ch in v):
            raise ValueError("key may only contain lowercase letters, numbers, underscores, and colons")
        return v


class AdminPermission(AdminPermissionBase, TimestampSchema):
    bit_index: int


class AdminPermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    name: str
    description: str | None


class AdminPermissionCreate(AdminPermissionBase):
    model_config = ConfigDict(extra="forbid")


class AdminPermissionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: Annotated[str | None, Field(min_length=3, max_length=100, examples=["update:post"], default=None)]
    name: Annotated[str | None, Field(min_length=3, max_length=100, examples=["Update Post"], default=None)]
    description: Annotated[str | None, Field(max_length=1_000, examples=["Updates posts"], default=None)]

    @field_validator("key", "name", "description", mode="before")
    @classmethod
    def normalize_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("key")
    @classmethod
    def validate_key_format(cls, v: str) -> str:
        if v is None:
            return v
        if not v.islower():
            raise ValueError("key must be lowercase")
        if any(ch.isspace() for ch in v):
            raise ValueError("key must not contain whitespace")
        allowed_chars = set("abcdefghijklmnopqrstuvwxyz0123456789_:")
        if not all(ch in allowed_chars for ch in v):
            raise ValueError("key may only contain lowercase letters, numbers, underscores, and colons")
        return v


class AdminPermissionBulkDelete(BaseModel):
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
