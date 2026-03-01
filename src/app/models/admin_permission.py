from typing import TYPE_CHECKING

from sqlalchemy import Index, Integer, Sequence, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, TimestampMixin
from ._rbac_table import admin_role_permission, admin_user_permission

if TYPE_CHECKING:
    from .admin_role import AdminRole
    from .admin_user import AdminUser

permission_bit_index_sequence = Sequence(
    "permission_bit_index_sequence",
    start=1,
    increment=1,
    metadata=Base.metadata,
)


class AdminPermission(IntegerPKMixin, TimestampMixin, Base):
    __tablename__ = "admin_permission"

    key: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)

    roles: Mapped[list["AdminRole"]] = relationship(
        "AdminRole",
        secondary=admin_role_permission,
        back_populates="permissions",
        lazy="raise",
        init=False,
    )
    admin_users: Mapped[list["AdminUser"]] = relationship(
        "AdminUser",
        secondary=admin_user_permission,
        secondaryjoin="and_(admin_user_permission.c.admin_user_id == AdminUser.id, AdminUser.is_deleted.is_(False))",
        back_populates="direct_permissions",
        lazy="raise",
        init=False,
    )

    description: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))
    bit_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=permission_bit_index_sequence.next_value(),
        init=False,
    )

    __table_args__ = (
        Index("uq_admin_permission_key", "key", unique=True),
        Index("uq_admin_permission_bit_index", "bit_index", unique=True),
    )
