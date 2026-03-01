import uuid as uuid_pkg
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Index, String, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid6 import uuid7

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, SoftDeleteMixin, TimestampMixin
from ..core.enums import AdminAccountStatus
from ..core.utils.google_cloud_storage import generate_view_signed_url
from ._rbac_tables import admin_user_permission, admin_user_role

if TYPE_CHECKING:
    from .admin_permission import AdminPermission
    from .admin_role import AdminRole


class AdminUser(IntegerPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "admin_user"

    username: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)

    roles: Mapped[list["AdminRole"]] = relationship(
        "AdminRole",
        secondary=admin_user_role,
        back_populates="admin_users",
        lazy="raise",
        init=False,
    )
    direct_permissions: Mapped[list["AdminPermission"]] = relationship(
        "AdminPermission",
        secondary=admin_user_permission,
        back_populates="admin_users",
        lazy="raise",
        init=False,
    )

    first_name: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))
    last_name: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))
    phone_number: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))
    profile_image_object_key: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )

    uuid: Mapped[uuid_pkg.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default_factory=uuid7, init=False)
    account_status: Mapped[AdminAccountStatus] = mapped_column(
        SQLEnum(
            AdminAccountStatus,
            name="admin_user_account_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=AdminAccountStatus.ACTIVE,
        server_default=text(f"'{AdminAccountStatus.ACTIVE.value}'::admin_user_account_status_enum"),
    )

    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    @property
    def profile_image_url(self) -> str | None:
        if not self.profile_image_object_key:
            return None

        return generate_view_signed_url(self.profile_image_object_key)

    __table_args__ = (
        Index("uq_admin_user_username_active", "username", unique=True, postgresql_where=text("is_deleted = false")),
        Index("uq_admin_user_email_active", "email", unique=True, postgresql_where=text("is_deleted = false")),
        Index(
            "uq_admin_user_phone_number_active",
            "phone_number",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("uq_admin_user_uuid", "uuid", unique=True),
        Index("idx_admin_user_account_status_active", "account_status", postgresql_where=text("is_deleted = false")),
    )
