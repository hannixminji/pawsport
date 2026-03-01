from typing import TYPE_CHECKING

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, SoftDeleteMixin, TimestampMixin
from ..core.enums import AllergenType, AllergySeverity

if TYPE_CHECKING:
    from .pet import Pet


class PetAllergy(IntegerPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "pet_allergy"

    pet_id: Mapped[int] = mapped_column(Integer, ForeignKey("pet.id", ondelete="CASCADE"), nullable=False)

    allergen: Mapped[str] = mapped_column(String, nullable=False)
    allergen_type: Mapped[AllergenType] = mapped_column(
        SQLEnum(
            AllergenType,
            name="pet_allergy_allergen_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    severity: Mapped[AllergySeverity] = mapped_column(
        SQLEnum(
            AllergySeverity,
            name="pet_allergy_severity_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )

    pet: Mapped["Pet"] = relationship("Pet", uselist=False, back_populates="allergies", lazy="raise", init=False)

    reaction: Mapped[str | None] = mapped_column(Text, nullable=True, default=None, server_default=text("NULL"))

    __table_args__ = (
        Index(
            "uq_pet_allergy_pet_id_allergen_active",
            "pet_id",
            "allergen",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("idx_pet_allergy_allergen_type_active", "allergen_type", postgresql_where=text("is_deleted = false")),
        Index("idx_pet_allergy_severity_active", "severity", postgresql_where=text("is_deleted = false")),
    )
