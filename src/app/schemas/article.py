from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema


class ArticleCategory(str, Enum):
    HEALTH = "health"
    CARE = "care"
    VET_VISIT = "vet_visit"
    TRAINING = "training"
    NUTRITION = "nutrition"


class ArticlePetType(str, Enum):
    DOG = "dog"
    CAT = "cat"
    BOTH = "both"


class ArticleBase(BaseModel):
    title: Annotated[str, Field(min_length=3, max_length=50, examples=["Vaccination Schedule 101"])]
    description: Annotated[
        str,
        Field(min_length=10, max_length=255, examples=["Everything you need to know to keep your pet protected."])
    ]
    content: Annotated[
        str,
        Field(min_length=20, examples=["Vaccinations help protect your pet from serious diseases..."])
    ]
    category: Annotated[ArticleCategory, Field(examples=[ArticleCategory.HEALTH])]
    pet_type: Annotated[ArticlePetType, Field(examples=[ArticlePetType.BOTH])]

    @field_validator("title", "description", "content", mode="before")
    @classmethod
    def normalize_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("category", "pet_type", mode="before")
    @classmethod
    def normalize_enum_fields(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v


class Article(TimestampSchema, ArticleBase, UUIDSchema, PersistentDeletion):
    pass


class ArticleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    content: str
    category: ArticleCategory
    pet_type: ArticlePetType


class ArticleCreate(ArticleBase):
    model_config = ConfigDict(extra="forbid")


class ArticleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str | None, Field(min_length=3, max_length=50, examples=["Updated title"], default=None)]
    description: Annotated[
        str | None,
        Field(min_length=10, max_length=255, examples=["Updated short preview text."], default=None)
    ]
    content: Annotated[str | None, Field(min_length=20, examples=["Updated full article content..."], default=None)]
    category: Annotated[ArticleCategory | None, Field(examples=[ArticleCategory.CARE], default=None)]
    pet_type: Annotated[ArticlePetType | None, Field(examples=[ArticlePetType.DOG], default=None)]

    @field_validator("title", "description", "content", mode="before")
    @classmethod
    def normalize_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v

    @field_validator("category", "pet_type", mode="before")
    @classmethod
    def normalize_enum_fields(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v
