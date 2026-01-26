from datetime import UTC, date, datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base

if TYPE_CHECKING:
    from .pet_inventory_image import PetInventoryImage
    from .user import User


class InventoryType(str, Enum):
    FOOD = "food"
    MEDICINE = "medicine"


class InventoryUnit(str, Enum):
    KG = "kg"
    G = "g"
    LB = "lb"
    PCS = "pcs"
    BOTTLES = "bottles"
    TABLETS = "tablets"
    ML = "ml"


class PetInventory(Base):
    __tablename__ = "pet_inventory"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)

    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    inventory_type: Mapped[InventoryType] = mapped_column(
        SQLEnum(InventoryType, name="pet_inventory_type_enum"),
        nullable=False,
        index=True
    )
    quantity: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    unit: Mapped[InventoryUnit] = mapped_column(
        SQLEnum(InventoryUnit, name="pet_inventory_unit_enum"),
        nullable=False
    )

    owner: Mapped["User"] = relationship("User", back_populates="pet_inventories", lazy="selectin", init=False)

    images: Mapped[list["PetInventoryImage"]] = relationship(
        "PetInventoryImage",
        primaryjoin="and_(PetInventory.id == PetInventoryImage.inventory_id, ~PetInventoryImage.is_deleted)",
        order_by="PetInventoryImage.sort_order.asc()",
        back_populates="inventory",
        cascade="delete, delete-orphan",
        lazy="selectin",
        init=False
    )

    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)

    @property
    def image_urls(self) -> list[str]:
        return [image.image_url for image in self.images]

    __table_args__ = (
        Index(
            "uq_pet_inventory_owner_id_item_name_active",
            "owner_id",
            "item_name",
            unique=True,
            postgresql_where=~is_deleted,
        ),
    )
