from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.db.models import TimestampMixin

if TYPE_CHECKING:
    from .mobile_user import MobileUser


class PetQRDefault(TimestampMixin, Base):
    __tablename__ = "pet_qr_default"

    owner_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("mobile_user.id", ondelete="CASCADE"),
        primary_key=True,
        init=False,
    )

    owner: Mapped["MobileUser"] = relationship(
        "MobileUser",
        uselist=False,
        back_populates="pet_qr_default",
        lazy="raise",
        init=False,
    )

    show_owner_name: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    show_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    show_phone_number: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    show_address: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
