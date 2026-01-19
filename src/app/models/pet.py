import uuid as uuid_pkg
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import UUID, Boolean, Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid6 import uuid7

from ..core.db.database import Base
from ..core.utils.google_cloud_storage import generate_view_signed_url
from .missing_report import MissingReportStatus

if TYPE_CHECKING:
    from .missing_report import MissingReport
    from .pet_allergy import PetAllergy
    from .pet_medical_condition import PetMedicalCondition
    from .pet_medication import PetMedication
    from .pet_profile_image import PetProfileImage
    from .pet_schedule import PetSchedule
    from .pet_vaccination_record import PetVaccinationRecord
    from .user import User


class Pet(Base):
    __tablename__ = "pet"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(25), nullable=False)
    type: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    breed: Mapped[str] = mapped_column(String(30), nullable=False)
    sex: Mapped[str] = mapped_column(String(6), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)

    owner: Mapped["User"] = relationship("User", back_populates="pets", lazy="selectin", init=False)
    profile_images: Mapped[list["PetProfileImage"]] = relationship(
        "PetProfileImage",
        primaryjoin="and_(Pet.id == PetProfileImage.pet_id, ~PetProfileImage.is_deleted)",
        order_by="(PetProfileImage.sort_order.asc(), PetProfileImage.created_at.desc())",
        back_populates="pet",
        cascade="delete, delete-orphan",
        lazy="selectin",
        init=False
    )
    vaccination_records: Mapped[list["PetVaccinationRecord"]] = relationship(
        "PetVaccinationRecord",
        primaryjoin="and_(Pet.id == PetVaccinationRecord.pet_id, ~PetVaccinationRecord.is_deleted)",
        back_populates="pet",
        cascade="all, delete-orphan",
        lazy="selectin",
        init=False
    )
    allergies: Mapped[list["PetAllergy"]] = relationship(
        "PetAllergy",
        primaryjoin="and_(Pet.id == PetAllergy.pet_id, ~PetAllergy.is_deleted)",
        back_populates="pet",
        cascade="all, delete-orphan",
        lazy="selectin",
        init=False
    )
    medications: Mapped[list["PetMedication"]] = relationship(
        "PetMedication",
        primaryjoin="and_(Pet.id == PetMedication.pet_id, ~PetMedication.is_deleted)",
        back_populates="pet",
        cascade="all, delete-orphan",
        lazy="selectin",
        init=False,
    )
    medical_conditions: Mapped[list["PetMedicalCondition"]] = relationship(
        "PetMedicalCondition",
        primaryjoin="and_(Pet.id == PetMedicalCondition.pet_id, ~PetMedicalCondition.is_deleted)",
        back_populates="pet",
        cascade="all, delete-orphan",
        lazy="selectin",
        init=False
    )
    schedules: Mapped[list["PetSchedule"]] = relationship(
        "PetSchedule",
        primaryjoin="and_(Pet.id == PetSchedule.pet_id, ~PetSchedule.is_deleted)",
        back_populates="pet",
        cascade="all, delete-orphan",
        lazy="selectin",
        init=False
    )
    missing_reports: Mapped[list["MissingReport"]] = relationship(
        "MissingReport",
        primaryjoin="and_(Pet.id == MissingReport.pet_id, ~MissingReport.is_deleted)",
        back_populates="pet",
        cascade="all, delete-orphan",
        lazy="selectin",
        init=False
    )

    weight_kg: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    color: Mapped[str | None] = mapped_column(String(30), nullable=True)
    markings: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_sterilized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    qr_code_image_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True, default=None)
    uuid: Mapped[uuid_pkg.UUID] = mapped_column(UUID(as_uuid=True), default_factory=uuid7, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)

    @property
    def profile_image_urls(self) -> list[str]:
        return [profile_image.image_url for profile_image in self.profile_images]

    @property
    def primary_profile_image_url(self) -> str | None:
        primary = next((profile_image for profile_image in self.profile_images if profile_image.is_primary), None)
        return primary.image_url if primary else None

    @property
    def qr_code_url(self) -> str | None:
        if not self.qr_code_image_object_key:
            return None

        return generate_view_signed_url(self.qr_code_image_object_key)

    @property
    def missing_status(self) -> MissingReportStatus | None:
        if not self.missing_reports:
            return None

        latest_missing_report = max(self.missing_reports, key=lambda mr: mr.created_at)
        return latest_missing_report.status
