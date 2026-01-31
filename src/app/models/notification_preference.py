from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base

if TYPE_CHECKING:
    from .user import User


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)

    feature: Mapped[str] = mapped_column(String(64), nullable=False)

    user: Mapped["User"] = relationship(
        "User",
        back_populates="notification_preferences",
        lazy="selectin",
        init=False
    )

    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)

    __table_args__ = (
        Index(
            "uq_notification_preference_user_feature_active",
            "user_id",
            "feature",
            unique=True,
            postgresql_where=~is_deleted,
        ),
        Index(
            "idx_notification_preference_user_enabled_active",
            "user_id",
            "is_enabled",
            postgresql_where=~is_deleted,
        ),
    )
