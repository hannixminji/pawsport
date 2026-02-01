import uuid as uuid_pkg
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from geoalchemy2 import Geography
from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import to_shape
from sqlalchemy import UUID, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid6 import uuid7

from ..core.db.database import Base

if TYPE_CHECKING:
    from .sighting_report_image import SightingReportImage


class SightingReport(Base):
    __tablename__ = "sighting_report"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    pet_type: Mapped[str] = mapped_column(String(3), index=True)
    sighted_at_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sighting_location: Mapped[WKBElement] = mapped_column(Geography(geometry_type="POINT", srid=4326))
    address: Mapped[str] = mapped_column(String(512))
    images: Mapped[list["SightingReportImage"]] = relationship(
        "SightingReportImage",
        primaryjoin=
            "and_(SightingReport.id == SightingReportImage.sighting_report_id, ~SightingReportImage.is_deleted)",
        order_by="(SightingReportImage.sort_order.asc(), SightingReportImage.created_at.desc())",
        back_populates="sighting_report",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        init=False,
    )

    description: Mapped[str | None] = mapped_column(String(2000), default=None)
    uuid: Mapped[uuid_pkg.UUID] = mapped_column(UUID(as_uuid=True), default_factory=uuid7, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)

    @property
    def location(self) -> dict[str, float]:
        point = to_shape(self.sighting_location)
        return {"latitude": point.y, "longitude": point.x}

    @property
    def image_urls(self) -> list[str]:
        return [image.image_url for image in self.images]

    __table_args__ = (
        Index("idx_sighting_report_location", "sighting_location", postgresql_using="gist"),
    )
