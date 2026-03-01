from enum import StrEnum


class FilterOp(StrEnum):
    EQ = "eq"
    NEQ = "neq"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    ILIKE = "ilike"
    IN = "in"
    NOT_IN = "not_in"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"


class GroupOp(StrEnum):
    AND = "and"
    OR = "or"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"
