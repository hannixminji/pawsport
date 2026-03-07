import functools
import json
import logging
import re
from collections.abc import AsyncGenerator, Callable
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from redis.asyncio import ConnectionPool, Redis

from ..exceptions.cache_exceptions import InvalidRequestError, MissingClientError

LOGGER = logging.getLogger(__name__)

pool: ConnectionPool | None = None
client: Redis | None = None


def _extract_data_inside_brackets(input_string: str) -> list[str]:
    data_inside_brackets = re.findall(r"{(.*?)}", input_string)
    return data_inside_brackets


def _construct_data_dict(data_inside_brackets: list[str], kwargs: dict[str, Any]) -> dict[str, Any]:
    data_dict = {}
    for key in data_inside_brackets:
        data_dict[key] = kwargs[key]
    return data_dict


def _format_prefix(prefix: str, kwargs: dict[str, Any]) -> str:
    data_inside_brackets = _extract_data_inside_brackets(prefix)
    data_dict = _construct_data_dict(data_inside_brackets, kwargs)
    formatted_prefix = prefix.format(**data_dict)
    return formatted_prefix


def _format_extra_data(to_invalidate_extra: dict[str, str], kwargs: dict[str, Any]) -> dict[str, Any]:
    formatted_extra = {}
    for prefix, id_template in to_invalidate_extra.items():
        formatted_prefix = _format_prefix(prefix, kwargs)
        resource_id_val = _extract_data_inside_brackets(id_template)[0]
        formatted_extra[formatted_prefix] = kwargs[resource_id_val]

    return formatted_extra


def _namespace_version_key(namespace: str) -> str:
    return f"{namespace}:version"


async def _get_namespace_version(namespace: str) -> int:
    if client is None:
        return 0
    try:
        v = await client.get(_namespace_version_key(namespace))
        return int(v) if v else 0
    except Exception:
        LOGGER.warning("Failed to get namespace version for namespace=%s", namespace, exc_info=True)
        return 0


async def _increment_namespace_version(namespace: str) -> None:
    if client is None:
        return
    try:
        await client.incr(_namespace_version_key(namespace))
    except Exception:
        LOGGER.warning("Failed to increment namespace version for namespace=%s", namespace, exc_info=True)


async def invalidate_namespace(namespace: str) -> None:
    await _increment_namespace_version(namespace)


async def _delete_keys_by_pattern(pattern: str) -> None:
    if client is None:
        return

    cursor = 0
    while True:
        cursor, keys = await client.scan(cursor, match=pattern, count=100)
        if keys:
            await client.delete(*keys)
        if cursor == 0:
            break


def _resolve_name(name: str, kwargs: dict[str, Any]) -> Any:
    if "." in name:
        obj_name, attr = name.split(".", 1)
        obj = kwargs.get(obj_name)
        return getattr(obj, attr) if obj is not None else None
    return kwargs[name]


def cache(
    key_prefix: str,
    resource_id_name: str | list[str] | None = None,
    resource_id: str | int | None = None,
    expiration: int = 3600,
    namespace: str | None = None,
    to_invalidate_extra: dict[str, Any] | None = None,
    pattern_to_invalidate_extra: list[str] | None = None,
    namespaces_to_invalidate: list[str] | None = None,
) -> Callable:
    def wrapper(func: Callable) -> Callable:
        @functools.wraps(func)
        async def inner(request: Request, *args: Any, **kwargs: Any) -> Any:
            if client is None:
                raise MissingClientError

            if resource_id_name:
                if isinstance(resource_id_name, list):
                    resolved_id = ":".join(str(_resolve_name(name, kwargs)) for name in resource_id_name)
                else:
                    resolved_id = _resolve_name(resource_id_name, kwargs)
            elif resource_id is not None:
                resolved_id = resource_id
            else:
                resolved_id = None

            formatted_key_prefix = _format_prefix(key_prefix, kwargs)

            if namespace:
                version = await _get_namespace_version(namespace)
                cache_key = (
                    f"{formatted_key_prefix}:v{version}"
                    + (f":{resolved_id}" if resolved_id is not None else "")
                )
            else:
                cache_key = f"{formatted_key_prefix}" + (f":{resolved_id}" if resolved_id is not None else "")

            if request.method == "GET":
                if (
                    to_invalidate_extra is not None
                    or pattern_to_invalidate_extra is not None
                    or namespaces_to_invalidate is not None
                ):
                    raise InvalidRequestError

                try:
                    cached_data = await client.get(cache_key)
                    if cached_data:
                        return json.loads(cached_data.decode())
                except Exception:
                    LOGGER.warning("Cache read failed for key=%s", cache_key, exc_info=True)

            result = await func(request, *args, **kwargs)

            if request.method == "GET":
                try:
                    serialized_data = json.dumps(jsonable_encoder(result))
                    await client.set(cache_key, serialized_data, ex=expiration)
                except Exception:
                    LOGGER.warning("Cache write failed for key=%s", cache_key, exc_info=True)

                return result

            else:
                try:
                    await client.delete(cache_key)

                    if to_invalidate_extra is not None:
                        formatted_extra = _format_extra_data(to_invalidate_extra, kwargs)
                        for prefix, resource_id_val in formatted_extra.items():
                            await client.delete(f"{prefix}:{resource_id_val}")

                    if pattern_to_invalidate_extra is not None:
                        for pattern in pattern_to_invalidate_extra:
                            formatted_pattern = _format_prefix(pattern, kwargs)
                            await _delete_keys_by_pattern(formatted_pattern + "*")

                    if namespaces_to_invalidate is not None:
                        for ns in namespaces_to_invalidate:
                            await _increment_namespace_version(ns)

                except Exception:
                    LOGGER.warning("Cache invalidation failed for key=%s", cache_key, exc_info=True)

            return result

        return inner

    return wrapper


async def async_get_redis() -> AsyncGenerator[Redis]:
    if pool is None:
        raise MissingClientError
    client = Redis(connection_pool=pool)
    try:
        yield client
    finally:
        await client.aclose()  # type: ignore
