from collections.abc import Iterable
from typing import Any


def apply_partial_update(
    *,
    target: Any,
    input: Any,
    exclude: Iterable[str] | None = None,
) -> None:
    excluded_fields = set(exclude or ())
    for field_name, field_value in input.model_dump(exclude_unset=True, exclude=excluded_fields).items():
        setattr(target, field_name, field_value)
