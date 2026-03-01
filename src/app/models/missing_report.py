from datetime import datetime
from typing import TYPE_CHECKING

from geoalchemy2 import Geography
from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import to_shape
from shapely.geometry import Point
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, and_, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, SoftDeleteMixin, TimestampMixin
from ..core.enums import MissingReportStatus

if TYPE_CHECKING:
    from .pet import Pet


class MissingReport(IntegerPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "missing_report"

    pet_id: Mapped[int] = mapped_column(Integer, ForeignKey("pet.id", ondelete="CASCADE"), nullable=False)

    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_location: Mapped[WKBElement] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=False,
    )
    last_seen_address: Mapped[str] = mapped_column(String, nullable=False)

    pet: Mapped["Pet"] = relationship("Pet", uselist=False, back_populates="missing_reports", lazy="raise", init=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None, server_default=text("NULL"))
    report_status: Mapped[MissingReportStatus] = mapped_column(
        SQLEnum(
            MissingReportStatus,
            name="missing_report_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=MissingReportStatus.LOST,
        server_default=text(f"'{MissingReportStatus.LOST.value}'::missing_report_status_enum"),
    )

    @property
    def last_seen_location_dict(self) -> dict[str, float]:
        point: Point = to_shape(self.last_seen_location)
        return {"latitude": point.y, "longitude": point.x}

    __table_args__ = (
        Index(
            "uq_missing_report_one_lost_per_pet_active",
            "pet_id",
            unique=True,
            postgresql_where=and_(report_status == MissingReportStatus.LOST, text("is_deleted = false")),
        ),
        Index("idx_missing_report_last_seen_at_active", "last_seen_at", postgresql_where=text("is_deleted = false")),
        Index(
            "idx_missing_report_last_seen_location_active",
            "last_seen_location",
            postgresql_using="gist",
            postgresql_where=text("is_deleted = false"),
        ),
        Index("idx_missing_report_status_active", "report_status", postgresql_where=text("is_deleted = false")),
    )
