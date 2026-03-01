from dataclasses import dataclass, field
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator

from .enums import FilterOp, GroupOp, SortOrder


@dataclass(slots=True, frozen=True)
class WhereRule:
    field: str
    op: FilterOp
    value: Any


@dataclass(slots=True, frozen=True)
class WhereNot:
    condition: "WhereNode"


@dataclass(slots=True, frozen=True)
class WhereGroup:
    op: GroupOp
    conditions: list["WhereNode"] = field(default_factory=list)


WhereNode: type = WhereRule | WhereNot | WhereGroup


class SearchRequest(BaseModel):
    model_config = {"frozen": True}

    page: Annotated[int, Field(ge=1, default=1)]
    items_per_page: Annotated[int, Field(ge=1, le=100, default=50)]
    sort_by: str | None = None
    sort_order: SortOrder = SortOrder.ASC
    where: WhereNode | None = None

    @field_validator("sort_by")
    @classmethod
    def _sort_by_not_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("'sort_by' must not be blank.")
        return v
