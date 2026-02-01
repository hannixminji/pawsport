from datetime import UTC, date, datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Index, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base

if TYPE_CHECKING:
    from .pet import Pet
    from .pet_vaccination_record_attachment import PetVaccinationRecordAttachment


class VaccineType(str, Enum):
    CORE = "core"
    NON_CORE = "non_core"


class PetVaccinationRecord(Base):
    __tablename__ = "pet_vaccination_record"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pet.id", ondelete="CASCADE"), nullable=False, index=True)

    vaccine_name: Mapped[str] = mapped_column(String(255), nullable=False)
    vaccine_type: Mapped[VaccineType] = mapped_column(
        SQLEnum(VaccineType, name="vaccine_type_enum"),
        nullable=False,
        index=True
    )
    date_administered: Mapped[date] = mapped_column(Date, nullable=False)

    pet: Mapped["Pet"] = relationship("Pet", back_populates="vaccination_records", lazy="selectin", init=False)

    attachments: Mapped[list["PetVaccinationRecordAttachment"]] = relationship(
        "PetVaccinationRecordAttachment",
        primaryjoin=(
            "and_("
            "PetVaccinationRecord.id == PetVaccinationRecordAttachment.vaccination_record_id, "
            "~PetVaccinationRecordAttachment.is_deleted"
            ")"
        ),
        order_by="PetVaccinationRecordAttachment.created_at.asc()",
        back_populates="vaccination_record",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        init=False
    )

    next_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)

    __table_args__ = (
        Index(
            "uq_pet_vaccination_record_pet_id_vaccine_name_active",
            "pet_id",
            "vaccine_name",
            unique=True,
            postgresql_where=~is_deleted,
        ),
    )
