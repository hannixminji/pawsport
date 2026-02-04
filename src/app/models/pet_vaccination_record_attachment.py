from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.utils.google_cloud_storage import generate_view_signed_url

if TYPE_CHECKING:
    from .pet_vaccination_record import PetVaccinationRecord


class AttachmentFileType(StrEnum):
    PDF = "pdf"
    JPG = "jpg"
    JPEG = "jpeg"
    PNG = "png"


class PetVaccinationRecordAttachment(Base):
    __tablename__ = "pet_vaccination_record_attachment"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    vaccination_record_id: Mapped[int] = mapped_column(
        ForeignKey("pet_vaccination_record.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)

    vaccination_record: Mapped["PetVaccinationRecord"] = relationship(
        "PetVaccinationRecord",
        back_populates="attachments",
        lazy="selectin",
        init=False
    )

    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_type: Mapped[AttachmentFileType | None] = mapped_column(
        SQLEnum(AttachmentFileType, name="vaccination_record_attachment_file_type"),
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)

    @property
    def attachment_url(self) -> str:
        return generate_view_signed_url(self.object_key)
