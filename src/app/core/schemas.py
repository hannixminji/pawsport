import uuid as uuid_pkg
from datetime import UTC, datetime
from typing import Annotated, Any, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, Field, SecretStr, field_serializer
from uuid6 import uuid7

from .enums import ActorType


def validate_strong_password(v: SecretStr) -> SecretStr:
    password = v.get_secret_value()
    errors = []
    if len(password) < 8:
        errors.append("at least 8 characters")
    if not any(c.isdigit() for c in password):
        errors.append("at least one digit")
    if not any(c.isupper() for c in password):
        errors.append("at least one uppercase letter")
    if not any(c.islower() for c in password):
        errors.append("at least one lowercase letter")
    if not any(not c.isalnum() for c in password):
        errors.append("at least one special character")
    if errors:
        raise ValueError(f"Password must contain: {', '.join(errors)}")
    return v


StrongPassword = Annotated[
    SecretStr,
    AfterValidator(validate_strong_password),
    Field(examples=["Str1ngst!"]),
]


class HealthCheck(BaseModel):
    status: str
    environment: str
    version: str
    timestamp: str


class ReadyCheck(BaseModel):
    status: str
    environment: str
    version: str
    app: str
    database: str
    redis: str
    timestamp: str


# -------------- mixins --------------
class UUIDSchema(BaseModel):
    uuid: uuid_pkg.UUID = Field(default_factory=uuid7)


class TimestampSchema(BaseModel):
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: datetime | None = Field(default=None)

    @field_serializer("created_at")
    def serialize_dt(self, created_at: datetime | None, _info: Any) -> str | None:
        if created_at is not None:
            return created_at.isoformat()

        return None

    @field_serializer("updated_at")
    def serialize_updated_at(self, updated_at: datetime | None, _info: Any) -> str | None:
        if updated_at is not None:
            return updated_at.isoformat()

        return None


class PersistentDeletion(BaseModel):
    deleted_at: datetime | None = Field(default=None)
    is_deleted: bool = False

    @field_serializer("deleted_at")
    def serialize_dates(self, deleted_at: datetime | None, _info: Any) -> str | None:
        if deleted_at is not None:
            return deleted_at.isoformat()

        return None


# -------------- pagination --------------
T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    data: list[T]
    total_count: int
    has_more: bool
    page: int
    items_per_page: int


# -------------- token --------------
class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username_or_email: str


class TokenBlacklistBase(BaseModel):
    token: str
    expires_at: datetime


class TokenBlacklistRead(TokenBlacklistBase):
    id: int


class TokenBlacklistCreate(TokenBlacklistBase):
    pass


class TokenBlacklistUpdate(TokenBlacklistBase):
    pass


class Actor(BaseModel):
    id: int
    actor_type: ActorType
    request_id: str
    is_superuser: bool
    role_ids: list[int] | None = None
    ip_address: str | None = None
    user_agent: str | None = None


class GeoPoint(BaseModel):
    latitude: Annotated[float, Field(ge=-90, le=90, examples=[37.7749])]
    longitude: Annotated[float, Field(ge=-180, le=180, examples=[-122.4194])]


class MapViewport(BaseModel):
    north: Annotated[float, Field(ge=-90, le=90, examples=[37.423])]
    south: Annotated[float, Field(ge=-90, le=90, examples=[37.419])]
    east: Annotated[float, Field(ge=-180, le=180, examples=[-122.082])]
    west: Annotated[float, Field(ge=-180, le=180, examples=[-122.087])]
    user_latitude: Annotated[float | None, Field(default=None, ge=-90, le=90, examples=[37.4219999])]
    user_longitude: Annotated[float | None, Field(default=None, ge=-180, le=180, examples=[-122.0840575])]
