from typing import TYPE_CHECKING

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, SoftDeleteMixin, TimestampMixin
from ..core.enums import AttachmentMimeType
from ..core.utils.google_cloud_storage import generate_view_signed_url

if TYPE_CHECKING:
    from .pet_vaccination_record import PetVaccinationRecord


class PetVaccinationRecordAttachment(IntegerPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "pet_vaccination_record_attachment"

    vaccination_record_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("pet_vaccination_record.id", ondelete="CASCADE"),
        nullable=False,
    )

    object_key: Mapped[str] = mapped_column(String, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    vaccination_record: Mapped["PetVaccinationRecord"] = relationship(
        "PetVaccinationRecord",
        uselist=False,
        back_populates="attachments",
        lazy="raise",
        init=False,
    )

    original_filename: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )
    mime_type: Mapped[AttachmentMimeType | None] = mapped_column(
        SQLEnum(
            AttachmentMimeType,
            name="pet_vaccination_record_attachment_mime_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )

    @property
    def attachment_url(self) -> str:
        return generate_view_signed_url(self.object_key)

    __table_args__ = (
        Index(
            "uq_pet_vaccination_record_attachment_sort_order_active",
            "vaccination_record_id",
            "sort_order",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
    )
