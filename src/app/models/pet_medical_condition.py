from datetime import UTC, date, datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Index, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base

if TYPE_CHECKING:
    from .pet import Pet


class MedicalConditionSeverity(str, Enum):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


class MedicalConditionStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    CHRONIC = "chronic"


class PetMedicalCondition(Base):
    __tablename__ = "pet_medical_condition"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pet.id", ondelete="CASCADE"), nullable=False, index=True)

    condition_name: Mapped[str] = mapped_column(String(255), nullable=False)
    severity_level: Mapped[MedicalConditionSeverity] = mapped_column(
        SQLEnum(MedicalConditionSeverity, name="pet_medical_condition_severity_enum"),
        nullable=False,
        index=True
    )
    condition_status: Mapped[MedicalConditionStatus] = mapped_column(
        SQLEnum(MedicalConditionStatus, name="pet_medical_condition_status_enum"),
        nullable=False,
        index=True
    )

    pet: Mapped["Pet"] = relationship("Pet", back_populates="medical_conditions", lazy="selectin", init=False)

    diagnosis_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)

    __table_args__ = (
        Index(
            "uq_pet_medical_condition_pet_id_condition_name_active",
            "pet_id",
            "condition_name",
            unique=True,
            postgresql_where=~is_deleted,
        ),
    )
