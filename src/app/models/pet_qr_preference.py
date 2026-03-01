from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.db.models import TimestampMixin

if TYPE_CHECKING:
    from .pet import Pet


class PetQRPreference(TimestampMixin, Base):
    __tablename__ = "pet_qr_preference"

    pet_id: Mapped[int] = mapped_column(Integer, ForeignKey("pet.id", ondelete="CASCADE"), primary_key=True, init=False)

    pet: Mapped["Pet"] = relationship("Pet", uselist=False, back_populates="qr_preference", lazy="raise", init=False)

    show_owner_name: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    show_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    show_phone_number: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    show_address: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    override_defaults: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
