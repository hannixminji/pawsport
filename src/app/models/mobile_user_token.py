from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin
from ..core.enums import UserTokenType

if TYPE_CHECKING:
    from .mobile_user import MobileUser


class MobileUserToken(IntegerPKMixin, Base):
    __tablename__ = "mobile_user_token"

    mobile_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("mobile_user.id", ondelete="CASCADE"),
        nullable=False,
    )

    type: Mapped[UserTokenType] = mapped_column(
        SQLEnum(
            UserTokenType,
            name="mobile_user_token_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    mobile_user: Mapped["MobileUser"] = relationship(
        "MobileUser",
        uselist=False,
        back_populates="tokens",
        lazy="raise",
        init=False,
    )

    payload_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        init=False,
    )

    __table_args__ = (
        Index("uq_mobile_user_token_hash", "token_hash", unique=True),
        Index("idx_mobile_user_token_mobile_user_id", "mobile_user_id"),
        Index("idx_mobile_user_token_type", "type"),
        Index("idx_mobile_user_token_expires_at", "expires_at"),
    )
