import uuid as uuid_pkg
from datetime import datetime
from typing import TYPE_CHECKING

from geoalchemy2 import Geography
from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import to_shape
from shapely.geometry import Point
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid6 import uuid7

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, SoftDeleteMixin, TimestampMixin
from ..core.utils.google_cloud_storage import generate_view_signed_url

if TYPE_CHECKING:
    from .device_push_token import DevicePushToken
    from .notification_preference import NotificationPreference
    from .pet import Pet
    from .pet_inventory import PetInventory
    from .pet_qr_default import PetQRDefault
    from .sighting_report import SightingReport
    from .tier import Tier
    from .user_linked_account import UserLinkedAccount


class MobileUser(IntegerPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "mobile_user"

    username: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)

    pets: Mapped[list["Pet"]] = relationship(
        "Pet",
        primaryjoin="and_(MobileUser.id == Pet.owner_id, Pet.is_deleted.is_(False))",
        back_populates="owner",
        cascade="delete, delete-orphan",
        lazy="raise",
        passive_deletes=True,
        init=False,
    )
    pet_inventories: Mapped[list["PetInventory"]] = relationship(
        "PetInventory",
        primaryjoin="and_(MobileUser.id == PetInventory.owner_id, PetInventory.is_deleted.is_(False))",
        back_populates="owner",
        cascade="delete, delete-orphan",
        lazy="raise",
        passive_deletes=True,
        init=False,
    )
    sighting_reports: Mapped[list["SightingReport"]] = relationship(
        "SightingReport",
        primaryjoin="and_(MobileUser.id == SightingReport.mobile_user_id, SightingReport.is_deleted.is_(False))",
        back_populates="mobile_user",
        cascade="delete",
        lazy="raise",
        passive_deletes=True,
        init=False,
    )
    linked_accounts: Mapped[list["UserLinkedAccount"]] = relationship(
        "UserLinkedAccount",
        primaryjoin="and_(MobileUser.id == UserLinkedAccount.mobile_user_id, UserLinkedAccount.is_deleted.is_(False))",
        back_populates="mobile_user",
        cascade="delete, delete-orphan",
        lazy="raise",
        passive_deletes=True,
        init=False,
    )
    device_push_tokens: Mapped[list["DevicePushToken"]] = relationship(
        "DevicePushToken",
        back_populates="mobile_user",
        cascade="delete, delete-orphan",
        lazy="raise",
        passive_deletes=True,
        init=False,
    )
    pet_qr_default: Mapped["PetQRDefault | None"] = relationship(
        "PetQRDefault",
        uselist=False,
        back_populates="owner",
        cascade="delete",
        lazy="raise",
        passive_deletes=True,
        init=False,
    )
    notification_preference: Mapped["NotificationPreference | None"] = relationship(
        "NotificationPreference",
        uselist=False,
        back_populates="mobile_user",
        cascade="delete",
        lazy="raise",
        passive_deletes=True,
        init=False,
    )

    tier_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("tier.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )

    first_name: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))
    last_name: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))
    phone_number: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))
    hashed_password: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )
    profile_image_object_key: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )

    country: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))
    street_address_1: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )
    street_address_2: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )
    city: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))
    state_province_region: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )
    postal_code: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )
    nearby_report_alert_location: Mapped[WKBElement | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )

    uuid: Mapped[uuid_pkg.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default_factory=uuid7, init=False)

    tier: Mapped["Tier | None"] = relationship(
        "Tier",
        uselist=False,
        back_populates="mobile_users",
        lazy="raise",
        init=False,
    )

    @property
    def profile_image_url(self) -> str | None:
        if not self.profile_image_object_key:
            return None

        return generate_view_signed_url(self.profile_image_object_key)

    @property
    def nearby_report_alert_location_dict(self) -> dict[str, float] | None:
        if self.nearby_report_alert_location is None:
            return None

        point: Point = to_shape(self.nearby_report_alert_location)
        return {"latitude": point.y, "longitude": point.x}

    __table_args__ = (
        Index("uq_mobile_user_username_active", "username", unique=True, postgresql_where=text("is_deleted = false")),
        Index("uq_mobile_user_email_active", "email", unique=True, postgresql_where=text("is_deleted = false")),
        Index(
            "uq_mobile_user_phone_number_active",
            "phone_number",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("uq_mobile_user_uuid", "uuid", unique=True),
        Index("idx_mobile_user_tier_id_active", "tier_id", postgresql_where=text("is_deleted = false")),
        Index(
            "idx_mobile_user_nearby_report_alert_location_active",
            "nearby_report_alert_location",
            postgresql_using="gist",
            postgresql_where=text("is_deleted = false"),
        ),
    )
