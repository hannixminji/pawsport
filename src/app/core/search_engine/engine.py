import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final, TypeVar, assert_never

from sqlalchemy import Select, and_, case, func, not_, null, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from ..exceptions.domain_exceptions import InvalidInputError
from .enums import FilterOp, GroupOp, SortOrder
from .schemas import SearchRequest, WhereGroup, WhereNode, WhereNot, WhereRule

type ColumnMap = dict[str, Any]
type SqlExpr = Any

_T = TypeVar("_T", bound=DeclarativeBase)
_S = TypeVar("_S")

GLOBAL_BLACKLISTED_COLUMNS: Final[frozenset[str]] = frozenset({
    "password",
    "hashed_password",
    "secret",
    "token",
})

_DEFAULT_MAX_IN_LIST_SIZE: Final[int] = 1_000
_DEFAULT_MAX_DEPTH: Final[int] = 20
_DEFAULT_SORT_BY: Final[str] = "created_at"
_DEFAULT_SORT_ORDER: Final[SortOrder] = SortOrder.DESC


@dataclass(slots=True, frozen=True)
class SearchResult[S]:
    data: list[S]
    total_count: int
    page: int
    items_per_page: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "data": self.data,
            "total_count": self.total_count,
            "page": self.page,
            "items_per_page": self.items_per_page,
        }


class SearchEngine[T: DeclarativeBase]:
    __slots__ = (
        "_allowed_ops",
        "_blacklisted",
        "_column_map",
        "_column_order_map",
        "_default_sort_by",
        "_default_sort_order",
        "_max_depth",
        "_max_in_list_size",
        "_sortable_columns",
        "db",
        "model",
    )

    def __init__(
        self,
        db: AsyncSession,
        model: type[T],
        *,
        blacklisted_columns: frozenset[str] | set[str] = frozenset(),
        allowed_ops: dict[str, frozenset[FilterOp]] | None = None,
        column_order_map: dict[str, list[Any]] | None = None,
        sortable_columns: frozenset[str] | set[str] | None = None,
        max_in_list_size: int | None = None,
        max_depth: int | None = None,
        default_sort_by: str | None = _DEFAULT_SORT_BY,
        default_sort_order: SortOrder = _DEFAULT_SORT_ORDER,
    ) -> None:
        self.db = db
        self.model = model

        self._blacklisted: frozenset[str] = GLOBAL_BLACKLISTED_COLUMNS | frozenset(blacklisted_columns)
        self._column_map: ColumnMap = self._build_column_map()
        self._allowed_ops: dict[str, frozenset[FilterOp]] = allowed_ops or {}
        self._column_order_map: dict[str, list[Any]] = column_order_map or {}
        self._sortable_columns: frozenset[str] | None = (
            frozenset(sortable_columns) - self._blacklisted if sortable_columns is not None else None
        )
        self._max_in_list_size: int = _DEFAULT_MAX_IN_LIST_SIZE if max_in_list_size is None else max_in_list_size
        self._max_depth: int = _DEFAULT_MAX_DEPTH if max_depth is None else max_depth
        self._default_sort_by: str | None = (
            default_sort_by if default_sort_by is not None and default_sort_by in self._column_map else None
        )
        self._default_sort_order: SortOrder = default_sort_order

    def _build_column_map(self) -> ColumnMap:
        return {attr.key: getattr(self.model, attr.key)
                for attr in self.model.__mapper__.column_attrs
                if attr.key not in self._blacklisted}

    def _resolve_column(self, name: str) -> SqlExpr:
        column = self._column_map.get(name)
        if column is None:
            raise InvalidInputError(f"Unknown or disallowed field: '{name}'.")
        return column

    async def search(
        self,
        *,
        base_query: Select[Any],
        values: SearchRequest,
        serializer: Callable[[T], _S],
    ) -> SearchResult[_S]:
        query = self._apply_filters(base_query, values.where, depth=0)
        count_query = select(func.count()).select_from(query.subquery())

        sort_by = values.sort_by if values.sort_by is not None else self._default_sort_by
        sort_order = values.sort_order if values.sort_by is not None else self._default_sort_order

        query = self._apply_ordering(query, sort_by, sort_order)
        paginated_query = query.offset(compute_offset(values.page, values.items_per_page)).limit(values.items_per_page)

        rows, total_count = await self._fetch(paginated_query, count_query)

        return SearchResult(
            data=[serializer(row) for row in rows],
            total_count=total_count,
            page=values.page,
            items_per_page=values.items_per_page,
        )

    def _apply_filters(self, query: Select[Any], where: WhereNode | None, depth: int) -> Select[Any]:
        if where is None:
            return query
        return query.where(self._build_where(where, depth))

    def _build_where(self, node: WhereNode, depth: int) -> SqlExpr:
        if depth >= self._max_depth:
            raise InvalidInputError(f"Filter nesting exceeds the maximum allowed depth of {self._max_depth}.")

        match node:
            case WhereRule():
                return self._build_rule(node)
            case WhereNot():
                return not_(self._build_where(node.condition, depth + 1))
            case WhereGroup():
                return self._build_group(node, depth + 1)
            case _ as unreachable:
                assert_never(unreachable)

    def _build_group(self, node: WhereGroup, depth: int) -> SqlExpr:
        match node.op:
            case GroupOp.AND:
                combiner = and_
            case GroupOp.OR:
                combiner = or_
            case _ as unreachable:
                assert_never(unreachable)

        if not node.conditions:
            raise InvalidInputError("A filter group must contain at least one condition.")

        return combiner(*(self._build_where(c, depth) for c in node.conditions))

    def _build_rule(self, node: WhereRule) -> SqlExpr:
        column = self._resolve_column(node.field)
        self._validate_operator(node.field, node.op)
        value = self._coerce_value(column, node.op, node.value)
        return self._apply_op(column, node.op, value)

    def _validate_operator(self, field: str, op: FilterOp) -> None:
        allowed = self._allowed_ops.get(field)
        if allowed is not None and op not in allowed:
            raise InvalidInputError(
                f"Operator '{op.value}' is not allowed on field '{field}'. "
                f"Allowed: {', '.join(o.value for o in sorted(allowed, key=lambda o: o.value))}."
            )

    def _apply_ordering(self, query: Select[Any], sort_by: str | None, sort_order: SortOrder) -> Select[Any]:
        if sort_by is None:
            return query

        if self._sortable_columns is not None and sort_by not in self._sortable_columns:
            raise InvalidInputError(
                f"Sorting by '{sort_by}' is not permitted. "
                f"Sortable fields: {', '.join(sorted(self._sortable_columns))}."
            )

        column = self._resolve_column(sort_by)
        custom_order = self._column_order_map.get(sort_by)

        if custom_order is not None:
            order_expr = case(*[(column == value, idx) for idx, value in enumerate(custom_order)], else_=null())
            expr = order_expr.asc().nulls_last() if sort_order == SortOrder.ASC else order_expr.desc().nulls_last()
            return query.order_by(expr)

        return query.order_by(column.asc() if sort_order == SortOrder.ASC else column.desc())

    def _coerce_value(self, column: SqlExpr, op: FilterOp, value: Any) -> Any:
        match op:
            case FilterOp.IS_NULL | FilterOp.IS_NOT_NULL:
                return None
            case FilterOp.IN | FilterOp.NOT_IN:
                return self._coerce_list(column, value)
            case FilterOp.ILIKE:
                if not isinstance(value, str):
                    raise InvalidInputError("ILIKE requires a string value.")
                return value
            case _:
                return self._coerce_scalar(column, value)

    def _coerce_list(self, column: SqlExpr, value: Any) -> list[Any]:
        if not isinstance(value, list):
            raise InvalidInputError("IN / NOT_IN requires a list value.")
        if not value:
            raise InvalidInputError("IN / NOT_IN requires a non-empty list.")

        deduped = list(dict.fromkeys(value))

        if len(deduped) > self._max_in_list_size:
            raise InvalidInputError(
                f"IN / NOT_IN list length {len(deduped):,} exceeds the maximum of {self._max_in_list_size:,}."
            )

        return [self._coerce_scalar(column, v) for v in deduped]

    @staticmethod
    def _coerce_scalar(column: SqlExpr, value: Any) -> Any:
        try:
            sa_type = column.property.columns[0].type
        except AttributeError as exc:
            raise InvalidInputError(f"Cannot introspect type for column '{column}': {exc}") from exc
        except IndexError as exc:
            raise InvalidInputError(f"Column '{column}' has no mapped physical column: {exc}") from exc

        enum_class: type | None = getattr(sa_type, "enum_class", None)
        if enum_class is None or isinstance(value, enum_class):
            return value

        if not isinstance(value, str):
            raise InvalidInputError(f"Expected a {enum_class.__name__} value, got {type(value).__name__}.")

        for candidate in (value, value.lower()):
            try:
                return enum_class(candidate)
            except ValueError:
                continue

        raise InvalidInputError(f"'{value}' is not a valid {enum_class.__name__}.")

    @staticmethod
    def _apply_op(column: SqlExpr, op: FilterOp, value: Any) -> SqlExpr:
        match op:
            case FilterOp.EQ:
                return column == value
            case FilterOp.NEQ:
                return column != value
            case FilterOp.LT:
                return column < value
            case FilterOp.LTE:
                return column <= value
            case FilterOp.GT:
                return column > value
            case FilterOp.GTE:
                return column >= value
            case FilterOp.ILIKE:
                safe_search = f"%{value.strip()}%"
                return column.ilike(safe_search)
            case FilterOp.IN:
                return column.in_(value)
            case FilterOp.NOT_IN:
                return column.notin_(value)
            case FilterOp.IS_NULL:
                return column.is_(None)
            case FilterOp.IS_NOT_NULL:
                return column.is_not(None)
            case _ as unreachable:
                assert_never(unreachable)

    async def _fetch(self, paginated_query: Select[Any], count_query: Select[Any]) -> tuple[Sequence[T], int]:
        data_result, count_result = await asyncio.gather(
            self.db.execute(paginated_query),
            self.db.execute(count_query),
        )
        return data_result.scalars().all(), count_result.scalar_one()


def compute_offset(page: int, items_per_page: int) -> int:
    if page < 1 or items_per_page < 1:
        raise InvalidInputError("Both 'page' and 'items_per_page' must be positive integers.")
    return (page - 1) * items_per_page
