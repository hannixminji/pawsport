from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Index, Integer, Sequence, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ._rbac_tables import role_permission, user_permission

if TYPE_CHECKING:
    from .role import Role
    from .user import User

permission_bit_index_sequence = Sequence(
    "permission_bit_index_sequence",
    start=1,
    increment=1,
    metadata=Base.metadata,
)


class Permission(Base):
    __tablename__ = "permission"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)

    key: Mapped[str] = mapped_column(String(50), nullable=False)

    roles: Mapped[list[Role]] = relationship(
        "Role",
        secondary=role_permission,
        back_populates="permissions",
        lazy="selectin",
        init=False,
    )
    users: Mapped[list[User]] = relationship(
        "User",
        secondary=user_permission,
        back_populates="direct_permissions",
        lazy="selectin",
        init=False,
    )

    bit_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=permission_bit_index_sequence.next_value(),
    )
    name: Mapped[str | None] = mapped_column(String(50), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    __table_args__ = (
        Index("uq_permission_key", "key", unique=True),
        Index("uq_permission_bit_index", "bit_index", unique=True),
    )
