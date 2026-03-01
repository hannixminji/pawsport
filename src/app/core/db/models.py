import uuid as uuid_pkg
from datetime import UTC, datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from uuid6 import uuid7


class IntegerPKMixin:
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        init=False,
    )


class UUIDMixin:
    uuid: Mapped[uuid_pkg.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid7,
        init=False,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        init=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        init=False,
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        init=False,
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        init=False,
    )

    __table_args__ = (
        CheckConstraint(
            "(is_deleted = false AND deleted_at IS NULL) OR "
            "(is_deleted = true AND deleted_at IS NOT NULL)",
            name="chk_softdelete_consistency",
        ),
    )

    def soft_delete(self) -> None:
        if not self.is_deleted or self.deleted_at is None:
            self.is_deleted = True
            if self.deleted_at is None:
                self.deleted_at = datetime.now(UTC)
