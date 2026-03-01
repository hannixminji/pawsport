from typing import TYPE_CHECKING

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, TimestampMixin
from ..core.enums import PushTokenPlatform, PushTokenProvider

if TYPE_CHECKING:
    from .mobile_user import MobileUser


class DevicePushToken(IntegerPKMixin, TimestampMixin, Base):
    __tablename__ = "device_push_token"

    mobile_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("mobile_user.id", ondelete="CASCADE"),
        nullable=False,
    )

    provider: Mapped[PushTokenProvider] = mapped_column(
        SQLEnum(
            PushTokenProvider,
            name="device_push_token_provider_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    platform: Mapped[PushTokenPlatform] = mapped_column(
        SQLEnum(
            PushTokenPlatform,
            name="device_push_token_platform_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    token: Mapped[str] = mapped_column(String, nullable=False)

    mobile_user: Mapped["MobileUser"] = relationship(
        "MobileUser",
        uselist=False,
        back_populates="device_push_tokens",
        lazy="raise",
        init=False,
    )

    __table_args__ = (
        Index("uq_device_push_token_provider_token", "provider", "token", unique=True),
        Index("idx_device_push_token_mobile_user_id", "mobile_user_id"),
    )
