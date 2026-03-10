import uuid as uuid_pkg
from datetime import datetime
from typing import TYPE_CHECKING

from geoalchemy2 import Geography
from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import to_shape
from shapely.geometry import Point
from sqlalchemy import UUID, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid6 import uuid7

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, SoftDeleteMixin, TimestampMixin
from ..core.enums import PetSpecies

if TYPE_CHECKING:
    from .mobile_user import MobileUser
    from .sighting_report_image import SightingReportImage


class SightingReport(IntegerPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "sighting_report"

    pet_species: Mapped[PetSpecies] = mapped_column(
        SQLEnum(
            PetSpecies,
            name="sighting_report_pet_species_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    sighted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sighting_location: Mapped[WKBElement] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=False,
    )
    sighting_address: Mapped[str] = mapped_column(String, nullable=False)

    images: Mapped[list["SightingReportImage"]] = relationship(
        "SightingReportImage",
        primaryjoin=(
            "and_(SightingReport.id == SightingReportImage.sighting_report_id, "
            "SightingReportImage.is_deleted.is_(False))"
        ),
        back_populates="sighting_report",
        order_by="SightingReportImage.sort_order.asc()",
        cascade="delete, delete-orphan",
        lazy="raise",
        passive_deletes=True,
        init=False,
    )

    mobile_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("mobile_user.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )

    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None, server_default=text("NULL"))

    mobile_user: Mapped["MobileUser | None"] = relationship(
        "MobileUser",
        uselist=False,
        back_populates="sighting_reports",
        lazy="raise",
        init=False,
    )

    reporter_name: Mapped[str | None] = mapped_column(Text, nullable=True, default=None, server_default=text("NULL"))
    reporter_email: Mapped[str | None] = mapped_column(Text, nullable=True, default=None, server_default=text("NULL"))
    reporter_phone_number: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )

    uuid: Mapped[uuid_pkg.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default_factory=uuid7, init=False)

    @property
    def sighting_location_dict(self) -> dict[str, float]:
        point: Point = to_shape(self.sighting_location)
        return {"latitude": point.y, "longitude": point.x}

    __table_args__ = (
        Index("idx_sighting_report_pet_species_active", "pet_species", postgresql_where=text("is_deleted = false")),
        Index("idx_sighting_report_sighted_at_active", "sighted_at", postgresql_where=text("is_deleted = false")),
        Index(
            "idx_sighting_report_sighting_location_active",
            "sighting_location",
            postgresql_using="gist",
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "idx_sighting_report_mobile_user_id_active",
            "mobile_user_id",
            postgresql_where=text("is_deleted = false"),
        ),
    )
