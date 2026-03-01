from typing import Any, NotRequired, TypedDict


class GetMultiResponse(TypedDict):
    data: list[Any]
    total_count: NotRequired[int]


def compute_offset(page: int, items_per_page: int) -> int:
    return (page - 1) * items_per_page


def paginated_response(
    data: GetMultiResponse | dict[str, Any],
    page: int,
    items_per_page: int,
    multi_response_key: str = "data",
) -> dict[str, Any]:
    items = data.get(multi_response_key, [])
    total_count = data.get("total_count", 0)

    return {
        multi_response_key: items,
        "total_count": total_count,
        "has_more": (page * items_per_page) < total_count,
        "page": page,
        "items_per_page": items_per_page,
    }
