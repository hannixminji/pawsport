import uuid as uuid_pkg
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import UUID, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid6 import uuid7

from ..core.db.database import Base
from ..core.utils.google_cloud_storage import generate_view_signed_url

if TYPE_CHECKING:
    from .sighting_report import SightingReport


class SightingReportImage(Base):
    __tablename__ = "sighting_report_image"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    sighting_report_id: Mapped[int] = mapped_column(ForeignKey("sighting_report.id", ondelete="CASCADE"), index=True)
    image_object_key: Mapped[str] = mapped_column(String(1024))
    sort_order: Mapped[int] = mapped_column(Integer)
    sighting_report: Mapped["SightingReport"] = relationship(
        "SightingReport",
        back_populates="images",
        lazy="selectin",
        init=False
    )

    uuid: Mapped[uuid_pkg.UUID] = mapped_column(UUID(as_uuid=True), default_factory=uuid7, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)

    @property
    def image_url(self) -> str:
        return generate_view_signed_url(self.image_object_key)
