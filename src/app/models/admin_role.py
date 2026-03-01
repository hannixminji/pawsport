from typing import TYPE_CHECKING

from sqlalchemy import Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, TimestampMixin
from ._rbac_tables import admin_role_permission, admin_user_role

if TYPE_CHECKING:
    from .admin_permission import AdminPermission
    from .admin_user import AdminUser


class AdminRole(IntegerPKMixin, TimestampMixin, Base):
    __tablename__ = "admin_role"

    name: Mapped[str] = mapped_column(String, nullable=False)

    admin_users: Mapped[list["AdminUser"]] = relationship(
        "AdminUser",
        secondary=admin_user_role,
        secondaryjoin="and_(admin_user_role.c.admin_user_id == AdminUser.id, AdminUser.is_deleted.is_(False))",
        back_populates="roles",
        lazy="raise",
        init=False,
    )
    permissions: Mapped[list["AdminPermission"]] = relationship(
        "AdminPermission",
        secondary=admin_role_permission,
        back_populates="roles",
        lazy="raise",
        init=False,
    )

    description: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))

    __table_args__ = (
        Index("uq_admin_role_name", "name", unique=True),
    )
