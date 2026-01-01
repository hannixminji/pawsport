from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema


class UserLinkedAccountBase(BaseModel):
    provider: Annotated[str, Field(min_length=1, max_length=15, examples=["google"])]
    provider_user_id: Annotated[str, Field(min_length=1, max_length=255, examples=["1234567890abcdef"])]


class UserLinkedAccount(TimestampSchema, UserLinkedAccountBase, UUIDSchema, PersistentDeletion):
    user_id: int


class UserLinkedAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    provider: str
    provider_user_id: str


class UserLinkedAccountCreate(UserLinkedAccountBase):
    model_config = ConfigDict(extra="forbid")


class UserLinkedAccountCreateInternal(UserLinkedAccountCreate):
    user_id: int


class UserLinkedAccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Annotated[
        str | None, Field(min_length=1, max_length=15, examples=["google"], default=None)
    ]
    provider_user_id: Annotated[
        str | None, Field(min_length=1, max_length=255, examples=["updated_provider_user_id"], default=None)
    ]


class UserLinkedAccountUpdateInternal(UserLinkedAccountUpdate):
    updated_at: datetime


class UserLinkedAccountDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime
