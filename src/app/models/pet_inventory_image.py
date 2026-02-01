from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db.database import Base
from ..core.utils.google_cloud_storage import generate_view_signed_url

if TYPE_CHECKING:
    from .pet_inventory import PetInventory


class InventoryImageFileType(str, Enum):
    JPG = "jpg"
    JPEG = "jpeg"
    PNG = "png"


class PetInventoryImage(Base):
    __tablename__ = "pet_inventory_image"

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    inventory_id: Mapped[int] = mapped_column(
        ForeignKey("pet_inventory.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    inventory: Mapped["PetInventory"] = relationship(
        "PetInventory",
        back_populates="images",
        lazy="selectin",
        init=False
    )

    file_type: Mapped[InventoryImageFileType | None] = mapped_column(
        SQLEnum(InventoryImageFileType, name="pet_inventory_image_file_type_enum"),
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)

    @property
    def image_url(self) -> str:
        return generate_view_signed_url(self.object_key)

    __table_args__ = (
        Index(
            "uq_pet_inventory_image_inventory_id_sort_order_active",
            "inventory_id",
            "sort_order",
            unique=True,
            postgresql_where=~is_deleted,
        ),
    )
