import uuid as uuid_pkg
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING

from geoalchemy2 import Geography
from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import to_shape
from sqlalchemy import UUID, DateTime, ForeignKey, Index, String, and_
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid6 import uuid7

from ..core.db.database import Base

if TYPE_CHECKING:
    from .pet import Pet


class MissingReportStatus(str, Enum):
    MISSING = "missing"
    FOUND = "found"
    RETURNED = "returned"
    CLOSED = "closed"


class MissingReport(Base):
    __tablename__ = "missing_report"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pet.id"), index=True)
    last_seen_location: Mapped[WKBElement] = mapped_column(Geography(geometry_type="POINT", srid=4326))
    last_seen_address: Mapped[str] = mapped_column(String(512))
    last_seen_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    contact_name: Mapped[str] = mapped_column(String(30))
    contact_number: Mapped[str] = mapped_column(String(20))
    pet: Mapped["Pet"] = relationship("Pet", back_populates="missing_reports", lazy="selectin", init=False)

    status: Mapped[MissingReportStatus] = mapped_column(
        SQLEnum(MissingReportStatus, name="missing_report_status"),
        default=MissingReportStatus.MISSING,
        index=True
    )
    contact_address: Mapped[str | None] = mapped_column(String(512), default=None)
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
        point = to_shape(self.last_seen_location)
        return {"latitude": point.y, "longitude": point.x}

    __table_args__ = (
        Index(
            "uq_active_missing_report_per_pet",
            "pet_id",
            unique=True,
            postgresql_where=and_(status.in_(["missing", "found"]), ~is_deleted)
        ),
        Index("idx_missing_report_location", "last_seen_location", postgresql_using="gist"),
    )
