from datetime import date, datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema


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
    quantity: Annotated[float, Field(ge=0, examples=[2.5])]
    unit: Annotated[InventoryUnit, Field(examples=[InventoryUnit.KG])]
    expiration_date: Annotated[date | None, Field(examples=["2026-12-31"], default=None)]

    @field_validator("item_name")
    @classmethod
    def normalize_item_name(cls, v: str) -> str:
        return v.strip()

    @field_validator("quantity")
    @classmethod
    def validate_quantity_by_unit(cls, v: float, info):
        unit = info.data.get("unit")
        if unit in {InventoryUnit.PCS, InventoryUnit.BOTTLES, InventoryUnit.TABLETS}:
            if not float(v).is_integer():
                raise ValueError("Quantity must be a whole number for pcs, bottles, or tablets")
        return v

    @field_validator("expiration_date")
    @classmethod
    def validate_expiration_date(cls, v: date | None) -> date | None:
        if v is None:
            return None
        if v < date.today():
            raise ValueError("Expiration date must be today or a future date")
        return v


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
    expiration_date: date | None


class PetInventoryCreate(PetInventoryBase):
    model_config = ConfigDict(extra="forbid")


class PetInventoryCreateInternal(PetInventoryCreate):
    owner_id: int


class PetInventoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_name: Annotated[str | None, Field(min_length=3, max_length=255, examples=["Dog Food"], default=None)]
    inventory_type: Annotated[InventoryType | None, Field(examples=[InventoryType.FOOD], default=None)]
    quantity: Annotated[float | None, Field(ge=0, examples=[2.5], default=None)]
    unit: Annotated[InventoryUnit | None, Field(examples=[InventoryUnit.KG], default=None)]
    expiration_date: Annotated[date | None, Field(examples=["2026-12-31"], default=None)]

    @field_validator("item_name")
    @classmethod
    def normalize_item_name(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v

    @field_validator("quantity")
    @classmethod
    def validate_quantity_by_unit(cls, v: float | None, info):
        if v is None:
            return v
        unit = info.data.get("unit")
        if unit in {InventoryUnit.PCS, InventoryUnit.BOTTLES, InventoryUnit.TABLETS}:
            if not float(v).is_integer():
                raise ValueError("Quantity must be a whole number for pcs, bottles, or tablets")
        return v

    @field_validator("expiration_date")
    @classmethod
    def validate_expiration_date(cls, v: date | None) -> date | None:
        if v is None:
            return None
        if v < date.today():
            raise ValueError("Expiration date must be today or a future date")
        return v


class PetInventoryUpdateInternal(PetInventoryUpdate):
    updated_at: datetime


class PetInventoryDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime
