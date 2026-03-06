from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, func, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base
from ..core.enums import ActionStatus


class SystemActionLog(Base):
    __tablename__ = "system_action_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, init=False)

    actor_type: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[ActionStatus] = mapped_column(
        SQLEnum(
            ActionStatus,
            name="system_action_log_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )

    is_superuser: Mapped[bool] = mapped_column(nullable=False, default=False, server_default=text("false"))
    is_anonymous: Mapped[bool] = mapped_column(nullable=False, default=False, server_default=text("false"))

    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None, server_default=text("NULL"))
    actor_email: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))
    role_ids: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True, default=None, server_default=text("NULL"))
    resource_type: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))
    resource_id: Mapped[str | None] = mapped_column(Text, nullable=True, default=None, server_default=text("NULL"))
    error_code: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None, server_default=text("NULL"))
    request_id: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True, default=None, server_default=text("NULL"))
    before_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None, server_default=text("NULL"))
    after_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None, server_default=text("NULL"))
    extra_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None, server_default=text("NULL"))
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None, server_default=text("NULL"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        init=False,
    )

    __table_args__ = (
        Index("idx_system_action_log_actor_id_created_at", "actor_id", "created_at"),
        Index(
            "idx_system_action_log_resource_type_resource_id_created_at",
            "resource_type",
            "resource_id",
            "created_at",
        ),
        Index("idx_system_action_log_action_created_at", "action", "created_at"),
        Index("idx_system_action_log_status_created_at", "status", "created_at"),
        Index("idx_system_action_log_request_id", "request_id"),
        Index("idx_system_action_log_failures", "status", "created_at", postgresql_where=text("status = 'FAILURE'")),
    )
