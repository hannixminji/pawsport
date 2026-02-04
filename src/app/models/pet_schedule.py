from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base

if TYPE_CHECKING:
    from .pet import Pet


class PetScheduleType(StrEnum):
    VET_VISIT = "vet_visit"
    VACCINATION = "vaccination"
    GROOMING = "grooming"
    FOOD = "food"
    WALK = "walk"
    MEDICINE = "medicine"
    PLAY_TIME = "play_time"
    OTHER = "other"


class PetSchedule(Base):
    __tablename__ = "pet_schedule"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pet.id", ondelete="CASCADE"), nullable=False, index=True)

    type: Mapped[PetScheduleType] = mapped_column(
        SQLEnum(PetScheduleType, name="pet_schedule_type_enum"),
        nullable=False,
        index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    pet: Mapped["Pet"] = relationship("Pet", back_populates="schedules", lazy="selectin", init=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    recurrence_rule: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    next_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)

    __table_args__ = (
        Index(
            "uq_pet_schedule_pet_id_title_active",
            "pet_id",
            "title",
            unique=True,
            postgresql_where=~is_deleted,
        ),
    )
