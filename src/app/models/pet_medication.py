from datetime import UTC, date, datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base

if TYPE_CHECKING:
    from .pet import Pet


class MedicationFrequency(str, Enum):
    ONCE_DAILY = "once_daily"
    TWICE_DAILY = "twice_daily"
    THREE_TIMES_DAILY = "three_times_daily"
    EVERY_OTHER_DAY = "every_other_day"
    WEEKLY = "weekly"
    AS_NEEDED = "as_needed"


class MedicationRoute(str, Enum):
    ORAL = "oral"
    TOPICAL = "topical"
    INJECTION = "injection"
    INHALATION = "inhalation"
    OCULAR = "ocular"
    OTIC = "otic"
    OTHER = "other"


class PetMedication(Base):
    __tablename__ = "pet_medication"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pet.id"), nullable=False, index=True)

    medication: Mapped[str] = mapped_column(String(255), nullable=False)
    dosage: Mapped[str] = mapped_column(String(100), nullable=False)
    frequency: Mapped[MedicationFrequency] = mapped_column(
        SQLEnum(MedicationFrequency, name="pet_medication_frequency_enum"),
        nullable=False,
        index=True
    )
    route: Mapped[MedicationRoute] = mapped_column(
        SQLEnum(MedicationRoute, name="pet_medication_route_enum"),
        nullable=False,
        index=True
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False)

    pet: Mapped["Pet"] = relationship("Pet", back_populates="medications", lazy="selectin", init=False)

    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
