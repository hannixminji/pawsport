from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ._rbac_tables import role_permission, user_role

if TYPE_CHECKING:
    from .permission import Permission
    from .user import User


class Role(Base):
    __tablename__ = "role"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)

    name: Mapped[str] = mapped_column(String(50), nullable=False)

    users: Mapped[list[User]] = relationship(
        "User",
        secondary=user_role,
        back_populates="roles",
        lazy="selectin",
        init=False,
    )
    permissions: Mapped[list[Permission]] = relationship(
        "Permission",
        secondary=role_permission,
        back_populates="roles",
        lazy="selectin",
        init=False,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    __table_args__ = (
        Index("uq_role_name", "name", unique=True),
    )
