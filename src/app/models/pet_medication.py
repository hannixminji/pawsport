from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, SoftDeleteMixin, TimestampMixin
from ..core.enums import MedicationAdministrationRoute, MedicationFrequency, MedicationStatus

if TYPE_CHECKING:
    from .pet import Pet


class PetMedication(IntegerPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "pet_medication"

    pet_id: Mapped[int] = mapped_column(Integer, ForeignKey("pet.id", ondelete="CASCADE"), nullable=False)

    medication_name: Mapped[str] = mapped_column(String, nullable=False)
    dosage: Mapped[str] = mapped_column(String, nullable=False)
    administration_route: Mapped[MedicationAdministrationRoute] = mapped_column(
        SQLEnum(
            MedicationAdministrationRoute,
            name="pet_medication_administration_route_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    frequency: Mapped[MedicationFrequency] = mapped_column(
        SQLEnum(
            MedicationFrequency,
            name="pet_medication_frequency_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    medication_status: Mapped[MedicationStatus] = mapped_column(
        SQLEnum(
            MedicationStatus,
            name="pet_medication_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )

    pet: Mapped["Pet"] = relationship("Pet", uselist=False, back_populates="medications", lazy="raise", init=False)

    end_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None, server_default=text("NULL"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None, server_default=text("NULL"))

    __table_args__ = (
        Index("idx_pet_medication_pet_id_active", "pet_id", postgresql_where=text("is_deleted = false")),
        Index(
            "idx_pet_medication_administration_route_active",
            "administration_route",
            postgresql_where=text("is_deleted = false"),
        ),
        Index("idx_pet_medication_status_active", "medication_status", postgresql_where=text("is_deleted = false")),
    )
