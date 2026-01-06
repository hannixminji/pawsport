import uuid as uuid_pkg
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid6 import uuid7

from ..core.db.database import Base
from ..core.utils.google_cloud_storage import generate_view_signed_url

if TYPE_CHECKING:
    from .pet import Pet
    from .user_linked_account import UserLinkedAccount


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(30))
    last_name: Mapped[str] = mapped_column(String(30))
    username: Mapped[str] = mapped_column(String(20), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    linked_accounts: Mapped[list["UserLinkedAccount"]] = relationship(
        "UserLinkedAccount",
        primaryjoin="and_(User.id == UserLinkedAccount.user_id, ~UserLinkedAccount.is_deleted)",
        back_populates="user",
        cascade="delete, delete-orphan",
        lazy="selectin",
        init=False
    )
    pets: Mapped[list["Pet"]] = relationship(
        "Pet",
        primaryjoin="and_(User.id == Pet.owner_id, ~Pet.is_deleted)",
        back_populates="owner",
        cascade="delete, delete-orphan",
        lazy="selectin",
        init=False
    )

    phone_number: Mapped[str | None] = mapped_column(String(20), default=None)
    hashed_password: Mapped[str | None] = mapped_column(String(255), default=None)
    profile_image_object_key: Mapped[str | None] = mapped_column(String(1024), default=None)
    country: Mapped[str | None] = mapped_column(String(60), default=None)
    street_address_1: Mapped[str | None] = mapped_column(String(255), default=None)
    street_address_2: Mapped[str | None] = mapped_column(String(255), default=None)
    city: Mapped[str | None] = mapped_column(String(100), default=None)
    state_province_region: Mapped[str | None] = mapped_column(String(100), default=None)
    postal_code: Mapped[str | None] = mapped_column(String(16), default=None)
    uuid: Mapped[uuid_pkg.UUID] = mapped_column(UUID(as_uuid=True), default_factory=uuid7, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    is_superuser: Mapped[bool] = mapped_column(default=False, nullable=False)
    tier_id: Mapped[int | None] = mapped_column(ForeignKey("tier.id"), init=False, default=None)

    @property
    def profile_image_url(self) -> str | None:
        if not self.profile_image_object_key:
            return None

        return generate_view_signed_url(self.profile_image_object_key)

    __table_args__ = (
        Index("uq_user_username_not_deleted", "username", unique=True, postgresql_where=~is_deleted),
        Index("uq_user_email_not_deleted", "email", unique=True, postgresql_where=~is_deleted),
        Index("uq_user_phone_not_deleted", "phone_number", unique=True, postgresql_where=~is_deleted),
    )
