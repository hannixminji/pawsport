from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base

if TYPE_CHECKING:
    from .user import User


class PushPlatform(str, Enum):
    ANDROID = "android"
    IOS = "ios"


class PushToken(Base):
    __tablename__ = "push_tokens"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)

    token: Mapped[str] = mapped_column(String(512), nullable=False)
    platform: Mapped[PushPlatform] = mapped_column(
        SQLEnum(PushPlatform, name="push_platform_enum"),
        nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="push_tokens", lazy="selectin", init=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)

    __table_args__ = (
        Index(
            "uq_push_tokens_token_active",
            "token",
            unique=True,
            postgresql_where=~is_deleted,
        ),
        Index(
            "idx_push_tokens_user_id_is_active_active",
            "user_id",
            "is_active",
            postgresql_where=~is_deleted,
        )
    )
