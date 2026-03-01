from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, Integer, String, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, SoftDeleteMixin, TimestampMixin
from ..core.enums import VaccineType

if TYPE_CHECKING:
    from .pet import Pet
    from .pet_vaccination_record_attachment import PetVaccinationRecordAttachment


class PetVaccinationRecord(IntegerPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "pet_vaccination_record"

    pet_id: Mapped[int] = mapped_column(Integer, ForeignKey("pet.id", ondelete="CASCADE"), nullable=False)

    vaccine_name: Mapped[str] = mapped_column(String, nullable=False)
    vaccine_type: Mapped[VaccineType] = mapped_column(
        SQLEnum(
            VaccineType,
            name="pet_vaccination_record_vaccine_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    administered_date: Mapped[date] = mapped_column(Date, nullable=False)

    pet: Mapped["Pet"] = relationship(
        "Pet",
        uselist=False,
        back_populates="vaccination_records",
        lazy="raise",
        init=False,
    )
    attachments: Mapped[list["PetVaccinationRecordAttachment"]] = relationship(
        "PetVaccinationRecordAttachment",
        primaryjoin=(
            "and_(PetVaccinationRecord.id == PetVaccinationRecordAttachment.vaccination_record_id, "
            "PetVaccinationRecordAttachment.is_deleted.is_(False))"
        ),
        back_populates="vaccination_record",
        cascade="delete, delete-orphan",
        lazy="raise",
        passive_deletes=True,
        init=False,
    )

    next_due_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None, server_default=text("NULL"))

    __table_args__ = (
        Index("idx_pet_vaccination_record_pet_id_active", "pet_id", postgresql_where=text("is_deleted = false")),
        Index(
            "idx_pet_vaccination_record_vaccine_type_active",
            "vaccine_type",
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "idx_pet_vaccination_record_next_due_date_active",
            "next_due_date",
            postgresql_where=text("is_deleted = false"),
        ),
    )
