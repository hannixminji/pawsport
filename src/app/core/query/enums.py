from __future__ import annotations

from enum import StrEnum


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class FilterOp(StrEnum):
    EQ = "eq"
    ILIKE = "ilike"
    GTE = "gte"
    LTE = "lte"
    IN = "in"
