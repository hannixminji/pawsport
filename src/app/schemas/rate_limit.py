import re
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.schemas import TimestampSchema

VALID_HTTP_METHODS = frozenset({"get", "post", "patch", "delete", "put"})
_SANITIZED_PATH_RE = re.compile(r"^[a-z0-9_{}]+$")


def sanitize_path(path: str) -> str:
    return path.strip("/").replace("/", "_").replace("-", "_")


def validate_path(path: str) -> str:
    sanitized = sanitize_path(path.strip())

    if not sanitized:
        raise ValueError("Path must not be empty after sanitization.")

    if not _SANITIZED_PATH_RE.match(sanitized):
        raise ValueError("Path may only contain lowercase letters, digits, and underscores.")

    parts = sanitized.split("_", 1)
    if parts[0] in VALID_HTTP_METHODS:
        if len(parts) == 1 or not parts[1]:
            raise ValueError(
                f"Path starts with HTTP method '{parts[0]}' but has no route after it."
            )

    return sanitized


class RateLimitBase(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=255, examples=["get_api_v1_medications:30:60"])]
    path: Annotated[str, Field(min_length=1, max_length=255, examples=["get_api_v1_medications"])]
    limit: Annotated[int, Field(ge=1, examples=[5])]
    period: Annotated[int, Field(ge=1, examples=[60])]

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("path", mode="before")
    @classmethod
    def validate_and_sanitize_path(cls, v: str) -> str:
        return validate_path(v)


class RateLimit(TimestampSchema, RateLimitBase):
    tier_id: int
    name: str


class RateLimitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tier_id: int
    name: str
    path: str
    limit: int
    period: int
    created_at: datetime


class RateLimitCreate(RateLimitBase):
    model_config = ConfigDict(extra="forbid")


class RateLimitUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[
        str | None,
        Field(min_length=1, max_length=255, examples=["get_api_v1_medications:30:60"], default=None),
    ]
    path: Annotated[
        str | None,
        Field(min_length=1, max_length=255, examples=["get_api_v1_medications"], default=None),
    ]
    limit: Annotated[int | None, Field(ge=1, examples=[10], default=None)]
    period: Annotated[int | None, Field(ge=1, examples=[120], default=None)]

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("path", mode="before")
    @classmethod
    def validate_and_sanitize_path(cls, v):
        if isinstance(v, str):
            return validate_path(v)
        return v


class RateLimitBulkDelete(BaseModel):
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
