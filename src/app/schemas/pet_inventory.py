import math
from datetime import date, datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema
from .pet_inventory_image import PetInventoryImageCreate, PetInventoryImageRead, PetInventoryImageUpdate


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


class PetInventoryBase(BaseModel):
    item_name: Annotated[str, Field(min_length=3, max_length=255, examples=["Dog Food"])]
    inventory_type: Annotated[InventoryType, Field(examples=[InventoryType.FOOD])]
    quantity: Annotated[float, Field(ge=0, le=100_000, examples=[2.5])]
    unit: Annotated[InventoryUnit, Field(examples=[InventoryUnit.KG])]
    expiration_date: Annotated[date | None, Field(examples=["2026-12-31"], default=None)]

    @field_validator("item_name", mode="before")
    @classmethod
    def normalize_item_name(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("inventory_type", "unit", mode="before")
    @classmethod
    def normalize_enum_fields(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_quantity(cls, v):
        try:
            x = float(v)
        except (TypeError, ValueError):
            return v

        if not math.isfinite(x):
            raise ValueError("quantity must be a finite number")

        if abs(x * 100 - round(x * 100)) > 1e-9:
            raise ValueError("quantity must have at most 2 decimal places")

        return x

    @field_validator("expiration_date")
    @classmethod
    def validate_expiration_date(cls, v: date | None) -> date | None:
        if v is not None and v < date.today():
            raise ValueError("Expiration date must be today or a future date")
        return v

    @model_validator(mode="after")
    def validate_quantity_by_unit(self):
        whole_units = {InventoryUnit.PCS, InventoryUnit.BOTTLES, InventoryUnit.TABLETS}
        if self.unit in whole_units and not float(self.quantity).is_integer():
            raise ValueError("Quantity must be a whole number for pcs, bottles, or tablets")
        return self


class PetInventory(TimestampSchema, PetInventoryBase, UUIDSchema, PersistentDeletion):
    owner_id: int


class PetInventoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    item_name: str
    inventory_type: InventoryType
    quantity: float
    unit: InventoryUnit
    images: list[PetInventoryImageRead]
    expiration_date: date | None


class PetInventoryCreate(PetInventoryBase):
    model_config = ConfigDict(extra="forbid")


class PetInventoryCreateInternal(PetInventoryBase):
    owner_id: int


class PetInventoryCreateWithImages(PetInventoryCreate):
    images: Annotated[list[PetInventoryImageCreate] | None, Field(default=None, max_length=5)]

    @field_validator("images", mode="after")
    @classmethod
    def validate_images_sort_order(cls, images):
        if images is None:
            return images

        if not images:
            return images

        sort_orders = [image.sort_order for image in images]

        if len(sort_orders) != len(set(sort_orders)):
            raise ValueError("Image order numbers must not have duplicates")

        return images


class PetInventoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_name: Annotated[str | None, Field(min_length=3, max_length=255, examples=["Dog Food"], default=None)]
    inventory_type: Annotated[InventoryType | None, Field(examples=[InventoryType.FOOD], default=None)]
    quantity: Annotated[float | None, Field(ge=0, le=100_000, examples=[2.5], default=None)]
    unit: Annotated[InventoryUnit | None, Field(examples=[InventoryUnit.KG], default=None)]
    expiration_date: Annotated[date | None, Field(examples=["2026-12-31"], default=None)]

    @field_validator("item_name", mode="before")
    @classmethod
    def normalize_item_name(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v

    @field_validator("inventory_type", "unit", mode="before")
    @classmethod
    def normalize_enum_fields(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_quantity(cls, v):
        try:
            x = float(v)
        except (TypeError, ValueError):
            return v

        if not math.isfinite(x):
            raise ValueError("quantity must be a finite number")

        if abs(x * 100 - round(x * 100)) > 1e-9:
            raise ValueError("quantity must have at most 2 decimal places")

        return x

    @field_validator("expiration_date")
    @classmethod
    def validate_expiration_date(cls, v: date | None) -> date | None:
        if v is not None and v < date.today():
            raise ValueError("Expiration date must be today or a future date")
        return v

    @model_validator(mode="after")
    def validate_quantity_unit_pair(self):
        if (self.quantity is None) != (self.unit is None):
            raise ValueError("quantity and unit must be provided together")
        return self

    @model_validator(mode="after")
    def validate_quantity_by_unit(self):
        if self.quantity is None or self.unit is None:
            return self

        whole_units = {InventoryUnit.PCS, InventoryUnit.BOTTLES, InventoryUnit.TABLETS}
        if self.unit in whole_units and not float(self.quantity).is_integer():
            raise ValueError("Quantity must be a whole number for pcs, bottles, or tablets")

        return self


class PetInventoryUpdateWithImages(PetInventoryUpdate):
    images: Annotated[list[PetInventoryImageUpdate] | None, Field(default=None, max_length=5)]

    @field_validator("images", mode="after")
    @classmethod
    def validate_images_sort_order(cls, images):
        if images is None:
            return images

        if not images:
            return images

        sort_orders = [image.sort_order for image in images]

        if len(sort_orders) != len(set(sort_orders)):
            raise ValueError("Image order numbers must not have duplicates")

        return images


class PetInventoryUpdateInternal(PetInventoryUpdate):
    updated_at: datetime


class PetInventoryDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime
