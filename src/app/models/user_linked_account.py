from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base

if TYPE_CHECKING:
    from .user import User


class UserLinkedAccount(Base):
    __tablename__ = "user_linked_account"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(25), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user: Mapped["User"] = relationship("User", back_populates="linked_accounts", lazy="selectin", init=False)

    provider_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)

    __table_args__ = (
        Index(
            "uq_user_linked_account",
            "provider",
            "provider_user_id",
            unique=True,
            postgresql_where=~is_deleted
        ),
    )
