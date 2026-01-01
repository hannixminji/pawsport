import uuid as uuid_pkg
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import UUID, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid6 import uuid7

from ..core.db.database import Base

if TYPE_CHECKING:
    from .user import User


class UserLinkedAccount(Base):
    __tablename__ = "user_linked_account"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(15), nullable=False, index=True)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user: Mapped["User"] = relationship("User", back_populates="linked_accounts", lazy="selectin", init=False)

    uuid: Mapped[uuid_pkg.UUID] = mapped_column(UUID(as_uuid=True), default_factory=uuid7, nullable=False, unique=True)
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
