import uuid as uuid_pkg
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import UUID, Boolean, Date, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid6 import uuid7

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, SoftDeleteMixin, TimestampMixin
from ..core.enums import PetSex, PetSpecies
from ..core.utils.google_cloud_storage import generate_view_signed_url

if TYPE_CHECKING:
    from .missing_report import MissingReport
    from .mobile_user import MobileUser
    from .pet_allergy import PetAllergy
    from .pet_medical_condition import PetMedicalCondition
    from .pet_medication import PetMedication
    from .pet_photo import PetPhoto
    from .pet_qr_preference import PetQRPreference
    from .pet_schedule import PetSchedule
    from .pet_vaccination_record import PetVaccinationRecord


class Pet(IntegerPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "pet"

    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("mobile_user.id", ondelete="CASCADE"), nullable=False)

    name: Mapped[str] = mapped_column(String, nullable=False)
    species: Mapped[PetSpecies] = mapped_column(
        SQLEnum(
            PetSpecies,
            name="pet_species_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    breed: Mapped[str] = mapped_column(String, nullable=False)
    sex: Mapped[PetSex] = mapped_column(
        SQLEnum(
            PetSex,
            name="pet_sex_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)

    owner: Mapped["MobileUser"] = relationship(
        "MobileUser",
        uselist=False,
        back_populates="pets",
        lazy="raise",
        init=False,
    )
    photos: Mapped[list["PetPhoto"]] = relationship(
        "PetPhoto",
        primaryjoin="and_(Pet.id == PetPhoto.pet_id, PetPhoto.is_deleted.is_(False))",
        back_populates="pet",
        order_by="PetPhoto.sort_order.asc()",
        cascade="delete, delete-orphan",
        lazy="raise",
        passive_deletes=True,
        init=False,
    )
    vaccination_records: Mapped[list["PetVaccinationRecord"]] = relationship(
        "PetVaccinationRecord",
        primaryjoin="and_(Pet.id == PetVaccinationRecord.pet_id, PetVaccinationRecord.is_deleted.is_(False))",
        back_populates="pet",
        cascade="delete, delete-orphan",
        lazy="raise",
        passive_deletes=True,
        init=False,
    )
    allergies: Mapped[list["PetAllergy"]] = relationship(
        "PetAllergy",
        primaryjoin="and_(Pet.id == PetAllergy.pet_id, PetAllergy.is_deleted.is_(False))",
        back_populates="pet",
        cascade="delete, delete-orphan",
        lazy="raise",
        passive_deletes=True,
        init=False,
    )
    medications: Mapped[list["PetMedication"]] = relationship(
        "PetMedication",
        primaryjoin="and_(Pet.id == PetMedication.pet_id, PetMedication.is_deleted.is_(False))",
        back_populates="pet",
        cascade="delete, delete-orphan",
        lazy="raise",
        passive_deletes=True,
        init=False,
    )
    medical_conditions: Mapped[list["PetMedicalCondition"]] = relationship(
        "PetMedicalCondition",
        primaryjoin="and_(Pet.id == PetMedicalCondition.pet_id, PetMedicalCondition.is_deleted.is_(False))",
        back_populates="pet",
        cascade="delete, delete-orphan",
        lazy="raise",
        passive_deletes=True,
        init=False,
    )
    schedules: Mapped[list["PetSchedule"]] = relationship(
        "PetSchedule",
        primaryjoin="and_(Pet.id == PetSchedule.pet_id, PetSchedule.is_deleted.is_(False))",
        back_populates="pet",
        cascade="delete, delete-orphan",
        lazy="raise",
        passive_deletes=True,
        init=False,
    )
    missing_reports: Mapped[list["MissingReport"]] = relationship(
        "MissingReport",
        primaryjoin="and_(Pet.id == MissingReport.pet_id, MissingReport.is_deleted.is_(False))",
        back_populates="pet",
        cascade="delete, delete-orphan",
        lazy="raise",
        passive_deletes=True,
        init=False,
    )
    qr_preference: Mapped["PetQRPreference | None"] = relationship(
        "PetQRPreference",
        uselist=False,
        back_populates="pet",
        cascade="delete",
        lazy="raise",
        passive_deletes=True,
        init=False,
    )

    color: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))
    markings: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))
    weight_kg: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2),
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )

    qr_code_object_key: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )
    uuid: Mapped[uuid_pkg.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default_factory=uuid7, init=False)

    is_sterilized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_missing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    @property
    def photo_urls(self) -> list[str]:
        return [photo.photo_url for photo in self.photos]

    @property
    def primary_photo_url(self) -> str | None:
        if self.photos:
            return self.photos[0].photo_url

        return None

    @property
    def qr_code_url(self) -> str | None:
        if not self.qr_code_object_key:
            return None

        return generate_view_signed_url(self.qr_code_object_key)

    __table_args__ = (
        Index("uq_pet_uuid", "uuid", unique=True),
        Index("uq_pet_qr_code_object_key", "qr_code_object_key", unique=True),
        Index("idx_pet_owner_id_active", "owner_id", postgresql_where=text("is_deleted = false")),
        Index("idx_pet_species_active", "species", postgresql_where=text("is_deleted = false")),
        Index("idx_pet_is_missing_active", "is_missing", postgresql_where=text("is_deleted = false")),
    )
