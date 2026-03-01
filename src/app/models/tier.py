from typing import TYPE_CHECKING

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, TimestampMixin

if TYPE_CHECKING:
    from .mobile_user import MobileUser
    from .rate_limit import RateLimit


class Tier(IntegerPKMixin, TimestampMixin, Base):
    __tablename__ = "tier"

    name: Mapped[str] = mapped_column(String, nullable=False)

    rate_limits: Mapped[list["RateLimit"]] = relationship(
        "RateLimit",
        back_populates="tier",
        cascade="delete, delete-orphan",
        lazy="raise",
        passive_deletes=True,
        init=False,
    )
    mobile_users: Mapped[list["MobileUser"]] = relationship(
        "MobileUser",
        primaryjoin="and_(Tier.id == MobileUser.tier_id, MobileUser.is_deleted.is_(False))",
        back_populates="tier",
        lazy="raise",
        init=False,
    )

    __table_args__ = (
        Index("uq_tier_name", "name", unique=True),
    )
