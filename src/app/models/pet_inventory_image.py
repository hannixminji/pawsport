from typing import TYPE_CHECKING

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, SoftDeleteMixin, TimestampMixin
from ..core.enums import MimeType
from ..core.utils.google_cloud_storage import generate_view_signed_url

if TYPE_CHECKING:
    from .pet_inventory import PetInventory


class PetInventoryImage(IntegerPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "pet_inventory_image"

    inventory_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("pet_inventory.id", ondelete="CASCADE"),
        nullable=False,
    )

    object_key: Mapped[str] = mapped_column(String, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    inventory: Mapped["PetInventory"] = relationship(
        "PetInventory",
        uselist=False,
        back_populates="images",
        lazy="raise",
        init=False,
    )

    mime_type: Mapped[MimeType | None] = mapped_column(
        SQLEnum(
            MimeType,
            name="pet_inventory_image_mime_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=True,
        default=None,
        server_default=text("NULL"),
    )

    @property
    def image_url(self) -> str:
        return generate_view_signed_url(self.object_key)

    __table_args__ = (
        Index(
            "uq_pet_inventory_image_inventory_id_sort_order_active",
            "inventory_id",
            "sort_order",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
    )
