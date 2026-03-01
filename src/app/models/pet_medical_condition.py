from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, SoftDeleteMixin, TimestampMixin
from ..core.enums import MedicalConditionSeverity, MedicalConditionStatus

if TYPE_CHECKING:
    from .pet import Pet


class PetMedicalCondition(IntegerPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "pet_medical_condition"

    pet_id: Mapped[int] = mapped_column(Integer, ForeignKey("pet.id", ondelete="CASCADE"), nullable=False)

    condition_name: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[MedicalConditionSeverity] = mapped_column(
        SQLEnum(
            MedicalConditionSeverity,
            name="pet_medical_condition_severity_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    condition_status: Mapped[MedicalConditionStatus] = mapped_column(
        SQLEnum(
            MedicalConditionStatus,
            name="pet_medical_condition_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )

    pet: Mapped["Pet"] = relationship(
        "Pet",
        uselist=False,
        back_populates="medical_conditions",
        lazy="raise",
        init=False,
    )

    diagnosis_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None, server_default=text("NULL"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None, server_default=text("NULL"))

    __table_args__ = (
        Index("idx_pet_medical_condition_pet_id_active", "pet_id", postgresql_where=text("is_deleted = false")),
        Index("idx_pet_medical_condition_severity_active", "severity", postgresql_where=text("is_deleted = false")),
        Index(
            "idx_pet_medical_condition_status_active",
            "condition_status",
            postgresql_where=text("is_deleted = false"),
        ),
    )
