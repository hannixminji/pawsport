from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, SoftDeleteMixin, TimestampMixin
from ..core.enums import PetScheduleType

if TYPE_CHECKING:
    from .pet import Pet


class PetSchedule(IntegerPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "pet_schedule"

    pet_id: Mapped[int] = mapped_column(Integer, ForeignKey("pet.id", ondelete="CASCADE"), nullable=False)

    title: Mapped[str] = mapped_column(String, nullable=False)
    schedule_type: Mapped[PetScheduleType] = mapped_column(
        SQLEnum(
            PetScheduleType,
            name="pet_schedule_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    pet: Mapped["Pet"] = relationship("Pet", uselist=False, back_populates="schedules", lazy="raise", init=False)

    recurrence_rule: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None, server_default=text("NULL"))

    is_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    __table_args__ = (
        Index("idx_pet_schedule_pet_id_active", "pet_id", postgresql_where=text("is_deleted = false")),
        Index("idx_pet_schedule_type_active", "schedule_type", postgresql_where=text("is_deleted = false")),
        Index("idx_pet_schedule_scheduled_at_active", "scheduled_at", postgresql_where=text("is_deleted = false")),
    )
