from typing import TYPE_CHECKING

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, SoftDeleteMixin, TimestampMixin
from ..core.enums import AuthProvider

if TYPE_CHECKING:
    from .mobile_user import MobileUser


class UserLinkedAccount(IntegerPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "user_linked_account"

    mobile_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("mobile_user.id", ondelete="CASCADE"),
        nullable=False,
    )

    provider: Mapped[AuthProvider] = mapped_column(
        SQLEnum(
            AuthProvider,
            name="user_linked_account_provider_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    provider_user_id: Mapped[str] = mapped_column(String, nullable=False)

    mobile_user: Mapped["MobileUser"] = relationship(
        "MobileUser",
        uselist=False,
        back_populates="linked_accounts",
        lazy="raise",
        init=False,
    )

    provider_email: Mapped[str | None] = mapped_column(String, nullable=True, default=None, server_default=text("NULL"))
    hashed_password: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )

    __table_args__ = (
        Index(
            "uq_user_linked_account_provider_provider_user_id_active",
            "provider",
            "provider_user_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "uq_user_linked_account_mobile_user_provider_active",
            "mobile_user_id",
            "provider",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "idx_user_linked_account_mobile_user_id_active",
            "mobile_user_id",
            postgresql_where=text("is_deleted = false"),
        ),
    )
