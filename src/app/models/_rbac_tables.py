from sqlalchemy import Column, ForeignKey, Table

from ..core.db.database import Base

admin_user_role = Table(
    "admin_user_role",
    Base.metadata,
    Column("admin_user_id", ForeignKey("admin_user.id", ondelete="CASCADE"), primary_key=True),
    Column("admin_role_id", ForeignKey("admin_role.id", ondelete="CASCADE"), primary_key=True),
)

admin_role_permission = Table(
    "admin_role_permission",
    Base.metadata,
    Column("admin_role_id", ForeignKey("admin_role.id", ondelete="CASCADE"), primary_key=True),
    Column("admin_permission_id", ForeignKey("admin_permission.id", ondelete="CASCADE"), primary_key=True),
)

admin_user_permission = Table(
    "admin_user_permission",
    Base.metadata,
    Column("admin_user_id", ForeignKey("admin_user.id", ondelete="CASCADE"), primary_key=True),
    Column("admin_permission_id", ForeignKey("admin_permission.id", ondelete="CASCADE"), primary_key=True),
)
