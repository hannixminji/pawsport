from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core.query.enums import FilterOp, SortOrder


class PetAllergySortBy(StrEnum):
    ALLERGEN = "allergen"
    ALLERGEN_TYPE = "allergen_type"
    SEVERITY_LEVEL = "severity_level"
    CREATED_AT = "created_at"


class PetAllergyFilterField(StrEnum):
    ALLERGEN = "allergen"
    ALLERGEN_TYPE = "allergen_type"
    SEVERITY_LEVEL = "severity_level"


class WhereRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["rule"]
    field: PetAllergyFilterField
    op: FilterOp
    value: Any


WhereNode = Annotated[Union[WhereRule, "WhereGroup", "WhereNot"], Field(discriminator="type")]  # noqa: UP037


class WhereGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["group"]
    op: Literal["and", "or"]
    conditions: list[WhereNode] = Field(min_length=1, max_length=50)


class WhereNot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["not"]
    condition: WhereNode


class PetAllergySearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1)
    items_per_page: int = Field(10, ge=1, le=100)

    sort_by: PetAllergySortBy = PetAllergySortBy.CREATED_AT
    sort_order: SortOrder = SortOrder.DESC

    where: WhereNode | None = None

    @model_validator(mode="after")
    def limit_complexity(self):
        def count_nodes(node: WhereNode, depth: int = 0) -> int:
            if depth > 10:
                raise ValueError("where is too deeply nested")

            if isinstance(node, WhereRule):
                return 1

            if isinstance(node, WhereNot):
                return 1 + count_nodes(node.condition, depth + 1)

            total = 1
            for child in node.conditions:
                total += count_nodes(child, depth + 1)
            return total

        if self.where is not None:
            total = count_nodes(self.where, 0)
            if total > 200:
                raise ValueError("where is too large")
        return self
