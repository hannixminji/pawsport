from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, TimestampMixin

if TYPE_CHECKING:
    from .tier import Tier


class RateLimit(IntegerPKMixin, TimestampMixin, Base):
    __tablename__ = "rate_limit"

    tier_id: Mapped[int] = mapped_column(Integer, ForeignKey("tier.id", ondelete="CASCADE"), nullable=False)

    name: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(String, nullable=False)
    limit: Mapped[int] = mapped_column(Integer, nullable=False)
    period: Mapped[int] = mapped_column(Integer, nullable=False)

    tier: Mapped["Tier"] = relationship("Tier", uselist=False, back_populates="rate_limits", lazy="raise", init=False)

    __table_args__ = (
        Index("uq_rate_limit_tier_id_name", "tier_id", "name", unique=True),
        Index("uq_rate_limit_tier_id_path", "tier_id", "path", unique=True),
    )
