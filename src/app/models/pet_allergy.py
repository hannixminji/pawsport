from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base

if TYPE_CHECKING:
    from .pet import Pet


class AllergenType(str, Enum):
    FOOD = "food"
    MEDICATION = "medication"
    ENVIRONMENTAL = "environmental"
    OTHER = "other"


class AllergySeverity(str, Enum):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


class PetAllergy(Base):
    __tablename__ = "pet_allergy"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pet.id"), nullable=False, index=True)

    allergen: Mapped[str] = mapped_column(String(255), nullable=False)
    allergen_type: Mapped[AllergenType] = mapped_column(
        SQLEnum(AllergenType, name="pet_allergen_type_enum"),
        nullable=False,
        index=True
    )
    severity_level: Mapped[AllergySeverity] = mapped_column(
        SQLEnum(AllergySeverity, name="pet_allergy_severity_enum"),
        nullable=False,
        index=True
    )

    pet: Mapped["Pet"] = relationship("Pet", back_populates="allergies", lazy="selectin", init=False)

    reaction: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
