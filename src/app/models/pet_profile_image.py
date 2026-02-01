import uuid as uuid_pkg
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import UUID, Boolean, DateTime, ForeignKey, Index, Integer, String, and_
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid6 import uuid7

from ..core.db.database import Base
from ..core.utils.google_cloud_storage import generate_view_signed_url

if TYPE_CHECKING:
    from .pet import Pet


class PetProfileImage(Base):
    __tablename__ = "pet_profile_image"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pet.id", ondelete="CASCADE"), nullable=False, index=True)
    image_object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    pet: Mapped["Pet"] = relationship("Pet", back_populates="profile_images", lazy="selectin", init=False)

    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    uuid: Mapped[uuid_pkg.UUID] = mapped_column(UUID(as_uuid=True), default_factory=uuid7, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)

    @property
    def image_url(self) -> str:
        return generate_view_signed_url(self.image_object_key)

    __table_args__ = (
        Index(
            "uq_pet_primary_image",
            "pet_id",
            unique=True,
            postgresql_where=and_(is_primary, ~is_deleted)
        ),
    )
