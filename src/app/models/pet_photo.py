import uuid as uuid_pkg
from typing import TYPE_CHECKING

from sqlalchemy import UUID, ForeignKey, Index, Integer, String, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid6 import uuid7

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, SoftDeleteMixin, TimestampMixin
from ..core.enums import MimeType
from ..core.utils.google_cloud_storage import generate_view_signed_url

if TYPE_CHECKING:
    from .pet import Pet


class PetPhoto(IntegerPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "pet_photo"

    pet_id: Mapped[int] = mapped_column(Integer, ForeignKey("pet.id", ondelete="CASCADE"), nullable=False)

    object_key: Mapped[str] = mapped_column(String, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    pet: Mapped["Pet"] = relationship("Pet", uselist=False, back_populates="photos", lazy="raise", init=False)

    mime_type: Mapped[MimeType | None] = mapped_column(
        SQLEnum(
            MimeType,
            name="pet_photo_mime_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )
    uuid: Mapped[uuid_pkg.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default_factory=uuid7, init=False)

    @property
    def photo_url(self) -> str:
        return generate_view_signed_url(self.object_key)

    __table_args__ = (
        Index(
            "uq_pet_photo_pet_id_sort_order_active",
            "pet_id",
            "sort_order",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
    )
