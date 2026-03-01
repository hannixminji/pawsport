from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.enums import ArticleCategory
from ..core.schemas import PersistentDeletion, TimestampSchema

TAG_MIN_LENGTH = 1
TAG_MAX_LENGTH = 30


class ArticleBase(BaseModel):
    title: Annotated[str, Field(min_length=3, max_length=50, examples=["Vaccination Schedule 101"])]
    content: Annotated[
        str,
        Field(
            min_length=1,
            max_length=10_000,
            examples=["Vaccinations help protect your pet from serious diseases..."],
        ),
    ]
    summary: Annotated[
        str | None,
        Field(
            min_length=1,
            max_length=500,
            examples=["Everything you need to know to keep your pet protected."],
            default=None,
        ),
    ]
    category: Annotated[ArticleCategory | None, Field(examples=[ArticleCategory.HEALTH], default=None)]
    tags: Annotated[list[str], Field(default_factory=list, max_length=10, examples=[["vaccination", "health"]])]

    @field_validator("title", "content", "summary", mode="before")
    @classmethod
    def normalize_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, v):
        if v is None:
            return []
        if isinstance(v, list):
            cleaned = [tag.strip() for tag in v if isinstance(tag, str) and tag.strip()]
            for tag in cleaned:
                if len(tag) < TAG_MIN_LENGTH or len(tag) > TAG_MAX_LENGTH:
                    raise ValueError(f"Each tag must be between {TAG_MIN_LENGTH} and {TAG_MAX_LENGTH} characters long")
            return cleaned
        return v


class Article(TimestampSchema, ArticleBase, PersistentDeletion):
    pass


class ArticleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    tags: list[str]
    created_at: datetime
    summary: str | None
    category: ArticleCategory | None


class ArticleCreate(ArticleBase):
    model_config = ConfigDict(extra="forbid")


class ArticleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str | None, Field(min_length=3, max_length=50, examples=["Updated title"], default=None)]
    content: Annotated[
        str | None,
        Field(
            min_length=1,
            max_length=10_000,
            examples=["Updated full article content..."],
            default=None,
        ),
    ]
    summary: Annotated[
        str | None,
        Field(
            min_length=1,
            max_length=500,
            examples=["Updated short preview text."],
            default=None,
        ),
    ]
    category: Annotated[ArticleCategory | None, Field(examples=[ArticleCategory.CARE], default=None)]
    tags: Annotated[list[str] | None, Field(examples=[["updated", "tags"]], default=None, max_length=10)]

    @field_validator("title", "content", "summary", mode="before")
    @classmethod
    def normalize_text_fields(cls, v):
        if isinstance(v, str):
            stripped = v.strip()
            return stripped if stripped else None
        return v

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, v):
        if v is None:
            return None
        if isinstance(v, list):
            cleaned = [tag.strip() for tag in v if isinstance(tag, str) and tag.strip()]
            for tag in cleaned:
                if len(tag) < TAG_MIN_LENGTH or len(tag) > TAG_MAX_LENGTH:
                    raise ValueError(f"Each tag must be between {TAG_MIN_LENGTH} and {TAG_MAX_LENGTH} characters long")
            return cleaned if cleaned else None
        return v
