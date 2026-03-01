from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.db.models import TimestampMixin

if TYPE_CHECKING:
    from .mobile_user import MobileUser


class NotificationPreference(TimestampMixin, Base):
    __tablename__ = "notification_preference"

    mobile_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("mobile_user.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )

    mobile_user: Mapped["MobileUser"] = relationship(
        "MobileUser",
        uselist=False,
        back_populates="notification_preference",
        lazy="raise",
        init=False,
    )

    nearby_report_alerts_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    pet_schedule_reminders_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )

    __table_args__ = (
        Index(
            "idx_notification_preference_nearby_report_alerts_enabled",
            "nearby_report_alerts_enabled",
            postgresql_where=nearby_report_alerts_enabled.is_(True),
        ),
    )
