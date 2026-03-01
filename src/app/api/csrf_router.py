from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.types import DecoratedCallable

from app.api.dependencies import require_admin_csrf_session

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class CSRFProtectedRouter(APIRouter):
    def add_api_route(
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        methods: list[str] | set[str] | None = None,
        dependencies: list[Depends] | None = None,  # type: ignore[type-arg]
        **kwargs: Any,
    ) -> None:
        normalised_methods = (
            {m.upper() for m in methods} if methods else {"GET"}
        )

        csrf_exempt: bool = getattr(endpoint, "_csrf_exempt", False)

        if not csrf_exempt and not normalised_methods.issubset(_SAFE_METHODS):
            dependencies = [
                Depends(require_admin_csrf_session),
                *(dependencies or []),
            ]

        super().add_api_route(
            path,
            endpoint,
            methods=normalised_methods,
            dependencies=dependencies,
            **kwargs,
        )

    def post(self, path: str, **kwargs: Any) -> Callable[[DecoratedCallable], DecoratedCallable]:
        return super().post(path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Callable[[DecoratedCallable], DecoratedCallable]:
        return super().put(path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Callable[[DecoratedCallable], DecoratedCallable]:
        return super().patch(path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Callable[[DecoratedCallable], DecoratedCallable]:
        return super().delete(path, **kwargs)


def csrf_exempt(func: DecoratedCallable) -> DecoratedCallable:
    func._csrf_exempt = True
    return func
