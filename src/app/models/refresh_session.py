from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin


class RefreshSession(IntegerPKMixin, Base):
    __tablename__ = "refresh_session"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("mobile_user.id", ondelete="CASCADE"), nullable=False)

    token_hash: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    device_id: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        init=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        server_default=text("NULL"),
        init=False,
    )

    __table_args__ = (
        Index("uq_refresh_session_token_hash", "token_hash", unique=True),
        Index("idx_refresh_session_user_id_revoked_at", "user_id", "revoked_at"),
    )
