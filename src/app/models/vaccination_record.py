import uuid as uuid_pkg
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import UUID, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid6 import uuid7

from ..core.db.database import Base
from ..core.utils.google_cloud_storage import generate_view_signed_url

if TYPE_CHECKING:
    from .pet import Pet


class VaccinationRecord(Base):
    __tablename__ = "vaccination_record"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pet.id"), nullable=False, index=True)
    file_object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)

    pet: Mapped["Pet"] = relationship(
        "Pet",
        back_populates="vaccination_records",
        lazy="selectin",
        init=False,
    )

    uuid: Mapped[uuid_pkg.UUID] = mapped_column(UUID(as_uuid=True), default_factory=uuid7, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)

    @property
    def file_url(self) -> str:
        return generate_view_signed_url(self.file_object_key)
