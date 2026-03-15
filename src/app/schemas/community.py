from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PostTag(StrEnum):
    LOST_PET = "lost_pet"
    FOUND_PET = "found_pet"
    ADOPTION = "adoption"
    ADVICE = "advice"
    GENERAL = "general"


class PostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    username: str
    user_profile_image: str
    text: str
    tag: PostTag = PostTag.GENERAL
    image_urls: list[str] = Field(default_factory=list)
    video_url: str | None = None
    likes_count: int = 0
    comments_count: int = 0
    is_pinned: bool = False
    is_announcement: bool = False
    is_locked: bool = False
    is_hidden: bool = False
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime | None = None


class PostCreate(BaseModel):
    user_id: str
    username: str
    user_profile_image: str
    text: str
    tag: PostTag = PostTag.GENERAL
    image_urls: list[str] = Field(default_factory=list)
    video_url: str | None = None


class PostUpdate(BaseModel):
    text: str | None = None
    tag: PostTag | None = None
    image_urls: list[str] | None = None
    video_url: str | None = None
    username: str | None = None
    user_profile_image: str | None = None


class PostBulkDelete(BaseModel):
    ids: set[str]


class PostTagUpdate(BaseModel):
    tag: PostTag


class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    post_id: str
    user_id: str
    username: str
    user_profile_image: str
    text: str
    likes_count: int = 0
    reply_count: int = 0
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime | None = None


class CommentCreate(BaseModel):
    user_id: str
    username: str
    user_profile_image: str
    text: str


class CommentUpdate(BaseModel):
    text: str | None = None
    username: str | None = None
    user_profile_image: str | None = None


class CommentBulkDelete(BaseModel):
    ids: set[str]


class ParticipantDetailRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    username: str
    user_profile_image: str


class ChatRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    participants: list[str]
    participant_details: dict[str, ParticipantDetailRead]
    last_message: str | None = None
    last_message_time: datetime | None = None
    seen_by: list[str] = Field(default_factory=list)


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chat_id: str
    sender_id: str
    text: str | None = None
    image_url: str | None = None
    created_at: datetime


class FirestoreUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    postgres_id: int | None = None
    username: str
    user_profile_image: str
    is_banned: bool = False
    is_muted: bool = False
    is_post_restricted: bool = False
    is_shadow_banned: bool = False
    warning_count: int = 0
    is_deleted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FirestoreUserUpdate(BaseModel):
    username: str | None = None
    user_profile_image: str | None = None


class WarnUserRead(BaseModel):
    warning_count: int
