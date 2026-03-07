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

    # Public Information
    show_owner_name: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    show_email: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    show_phone_number: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    show_address: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # Pet Details
    show_pet_name: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    show_pet_breed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    show_pet_age: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    show_pet_sex: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    show_pet_weight: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    show_pet_color: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    show_pet_markings: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    show_pet_sterilized: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    # Health Records
    show_medications: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    show_vaccines: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    show_allergies: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
