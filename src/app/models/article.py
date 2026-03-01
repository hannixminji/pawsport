from sqlalchemy import Enum as SQLEnum
from sqlalchemy import Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, SoftDeleteMixin, TimestampMixin
from ..core.enums import ArticleCategory


class Article(IntegerPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "article"

    title: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    category: Mapped[ArticleCategory | None] = mapped_column(
        SQLEnum(
            ArticleCategory,
            name="article_category_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=True,
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True, default=None, server_default=text("NULL"))
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))

    __table_args__ = (
        Index("uq_article_title_active", "title", unique=True, postgresql_where=text("is_deleted = false")),
        Index("idx_article_category_active", "category", postgresql_where=text("is_deleted = false")),
        Index("idx_article_tags_active", "tags", postgresql_using="gin", postgresql_where=text("is_deleted = false")),
    )
