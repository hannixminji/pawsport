from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..core.enums import InventoryType, InventoryUnit
from ..core.schemas import PersistentDeletion, TimestampSchema
from .pet_inventory_image import PetInventoryImageCreate, PetInventoryImageRead, PetInventoryImageUpdate


class PetInventoryBase(BaseModel):
    name: Annotated[str, Field(min_length=3, max_length=255, examples=["Dog Food"])]
    inventory_type: Annotated[InventoryType, Field(examples=[InventoryType.FOOD])]
    quantity: Annotated[Decimal, Field(ge=0, le=100_000, decimal_places=2, examples=[2.5])]
    unit: Annotated[InventoryUnit, Field(examples=[InventoryUnit.KG])]
    expiration_date: Annotated[date | None, Field(examples=["2026-12-31"], default=None)]
    notes: Annotated[str | None, Field(max_length=1000, examples=["Store in a cool place"], default=None)]

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v):
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
        if v is None:
            return v
        try:
            d = Decimal(str(v)) if not isinstance(v, Decimal) else v
        except (TypeError, ValueError, ArithmeticError):
            raise ValueError("quantity must be a valid decimal number")

        if d.as_tuple().exponent < -2:
            raise ValueError("quantity must have at most 2 decimal places")

        return d

    @field_validator("expiration_date")
    @classmethod
    def validate_expiration_date(cls, v: date | None) -> date | None:
        if v is not None and v < date.today():
            raise ValueError("expiration_date must be today or a future date")
        return v

    @model_validator(mode="after")
    def validate_quantity_by_unit(self):
        whole_units = {InventoryUnit.PCS, InventoryUnit.BOTTLES, InventoryUnit.TABLETS}
        if self.unit in whole_units and self.quantity != int(self.quantity):
            raise ValueError("quantity must be a whole number for pcs, bottles, or tablets")
        return self


class PetInventory(TimestampSchema, PetInventoryBase, PersistentDeletion):
    owner_id: int


class PetInventoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    name: str
    inventory_type: InventoryType
    quantity: Decimal
    unit: InventoryUnit
    images: list[PetInventoryImageRead]
    created_at: datetime
    expiration_date: date | None
    notes: str | None


class PetInventoryCreate(PetInventoryBase):
    model_config = ConfigDict(extra="forbid")


class PetInventoryCreateWithImages(PetInventoryCreate):
    images: Annotated[list[PetInventoryImageCreate] | None, Field(default=None, max_length=5)]

    @field_validator("images", mode="after")
    @classmethod
    def validate_images(cls, images):
        if images is None:
            return images

        if not images:
            return images

        object_keys = [image.object_key for image in images]
        if len(object_keys) != len(set(object_keys)):
            raise ValueError("image object_key must be unique")

        sort_orders = [image.sort_order for image in images]
        if len(sort_orders) != len(set(sort_orders)):
            raise ValueError("image sort_order must be unique")

        return images


class PetInventoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str | None, Field(min_length=3, max_length=255, examples=["Dog Food"], default=None)]
    inventory_type: Annotated[InventoryType | None, Field(examples=[InventoryType.FOOD], default=None)]
    quantity: Annotated[Decimal | None, Field(ge=0, le=100_000, decimal_places=2, examples=[2.5], default=None)]
    unit: Annotated[InventoryUnit | None, Field(examples=[InventoryUnit.KG], default=None)]
    expiration_date: Annotated[date | None, Field(examples=["2026-12-31"], default=None)]
    notes: Annotated[str | None, Field(max_length=1000, examples=["Updated notes"], default=None)]

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v):
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
        if v is None:
            return None
        try:
            d = Decimal(str(v)) if not isinstance(v, Decimal) else v
        except (TypeError, ValueError, ArithmeticError):
            raise ValueError("quantity must be a valid decimal number")

        if d.as_tuple().exponent < -2:
            raise ValueError("quantity must have at most 2 decimal places")

        return d

    @field_validator("expiration_date")
    @classmethod
    def validate_expiration_date(cls, v: date | None) -> date | None:
        if v is not None and v < date.today():
            raise ValueError("expiration_date must be today or a future date")
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
        if self.unit in whole_units and self.quantity != int(self.quantity):
            raise ValueError("quantity must be a whole number for pcs, bottles, or tablets")
        return self


class PetInventoryUpdateWithImages(PetInventoryUpdate):
    images: Annotated[list[PetInventoryImageUpdate] | None, Field(default=None, max_length=5)]

    @field_validator("images", mode="after")
    @classmethod
    def validate_images(cls, images):
        if images is None:
            return images

        if not images:
            return images

        image_ids = [image.id for image in images if image.id is not None]
        if len(image_ids) != len(set(image_ids)):
            raise ValueError("duplicate image ids are not allowed")

        object_keys = [image.object_key for image in images if image.object_key is not None]
        if len(object_keys) != len(set(object_keys)):
            raise ValueError("duplicate object keys are not allowed")

        sort_orders = [image.sort_order for image in images]
        if len(sort_orders) != len(set(sort_orders)):
            raise ValueError("image sort_order must be unique")

        return images
