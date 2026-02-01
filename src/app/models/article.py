from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base


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


class Article(Base):
    __tablename__ = "article"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)

    title: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    category: Mapped[ArticleCategory] = mapped_column(
        SQLEnum(ArticleCategory, name="article_category_enum"),
        nullable=False,
        index=True,
    )
    pet_type: Mapped[ArticlePetType] = mapped_column(
        SQLEnum(ArticlePetType, name="article_pet_type_enum"),
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)

    __table_args__ = (
        Index(
            "uq_article_title_active",
            "title",
            unique=True,
            postgresql_where=~is_deleted,
        ),
    )
