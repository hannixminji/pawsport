from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.db.models import IntegerPKMixin, SoftDeleteMixin, TimestampMixin
from ..core.enums import InventoryType, InventoryUnit

if TYPE_CHECKING:
    from .mobile_user import MobileUser
    from .pet_inventory_image import PetInventoryImage


class PetInventory(IntegerPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "pet_inventory"

    owner_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("mobile_user.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String, nullable=False)
    inventory_type: Mapped[InventoryType] = mapped_column(
        SQLEnum(
            InventoryType,
            name="pet_inventory_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    unit: Mapped[InventoryUnit] = mapped_column(
        SQLEnum(
            InventoryUnit,
            name="pet_inventory_unit_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )

    owner: Mapped["MobileUser"] = relationship(
        "MobileUser",
        uselist=False,
        back_populates="pet_inventories",
        lazy="raise",
        init=False,
    )
    images: Mapped[list["PetInventoryImage"]] = relationship(
        "PetInventoryImage",
        primaryjoin="and_(PetInventory.id == PetInventoryImage.inventory_id, PetInventoryImage.is_deleted.is_(False))",
        back_populates="inventory",
        order_by="PetInventoryImage.sort_order.asc()",
        cascade="delete, delete-orphan",
        lazy="raise",
        passive_deletes=True,
        init=False,
    )

    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None, server_default=text("NULL"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None, server_default=text("NULL"))

    @property
    def image_urls(self) -> list[str]:
        return [image.image_url for image in self.images]

    __table_args__ = (
        Index(
            "uq_pet_inventory_owner_id_name_active",
            "owner_id",
            "name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("idx_pet_inventory_type_active", "inventory_type", postgresql_where=text("is_deleted = false")),
        Index(
            "idx_pet_inventory_expiration_date_active",
            "expiration_date",
            postgresql_where=text("is_deleted = false"),
        ),
    )
