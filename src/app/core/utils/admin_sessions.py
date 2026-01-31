import json
import secrets
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

SESSION_COOKIE_NAME = "admin_session"
CSRF_COOKIE_NAME = "admin_csrf"


def _session_key(session_id: str) -> str:
    return f"admin:session:{session_id}"


def _csrf_key(session_id: str) -> str:
    return f"admin:csrf:{session_id}"


def current_timestamp_seconds() -> int:
    return int(datetime.now(UTC).timestamp())


def _effective_ttl_seconds(created_at: int, sliding_ttl_seconds: int, absolute_ttl_seconds: int) -> int:
    now = current_timestamp_seconds()
    age = max(0, now - created_at)
    remaining = absolute_ttl_seconds - age
    if remaining <= 0:
        return 0
    return min(sliding_ttl_seconds, remaining)


async def create_session(
    redis: Redis,
    user_id: int,
    sliding_ttl_seconds: int,
    absolute_ttl_seconds: int,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    session_id = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)

    created_at = current_timestamp_seconds()
    payload: dict[str, Any] = {
        "user_id": user_id,
        "created_at": created_at,
    }
    if metadata:
        payload.update(metadata)

    raw_payload = json.dumps(payload, separators=(",", ":"), default=str)
    expiration_seconds = min(sliding_ttl_seconds, absolute_ttl_seconds)

    async with redis.pipeline(transaction=True) as pipe:
        pipe.set(_session_key(session_id), raw_payload, ex=expiration_seconds)
        pipe.set(_csrf_key(session_id), csrf_token, ex=expiration_seconds)
        await pipe.execute()

    return session_id, csrf_token


async def read_session(redis: Redis, session_id: str) -> dict[str, Any] | None:
    raw = await redis.get(_session_key(session_id))
    if not raw:
        return None

    if isinstance(raw, bytes):
        raw = raw.decode()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    return data


async def delete_session(redis: Redis, session_id: str) -> None:
    async with redis.pipeline(transaction=True) as pipe:
        pipe.delete(_session_key(session_id))
        pipe.delete(_csrf_key(session_id))
        await pipe.execute()


async def refresh_session(
    redis: Redis,
    session_id: str,
    sliding_ttl_seconds: int,
    absolute_ttl_seconds: int,
) -> bool:
    session = await read_session(redis, session_id)
    if not session:
        await delete_session(redis, session_id)
        return False

    created_at = session["created_at"]
    expiration_seconds = _effective_ttl_seconds(created_at, sliding_ttl_seconds, absolute_ttl_seconds)
    if expiration_seconds <= 0:
        await delete_session(redis, session_id)
        return False

    async with redis.pipeline(transaction=True) as pipe:
        pipe.expire(_session_key(session_id), expiration_seconds)
        pipe.expire(_csrf_key(session_id), expiration_seconds)
        await pipe.execute()

    return True


async def validate_csrf(
    redis: Redis,
    session_id: str,
    csrf_token_from_header: str | None,
) -> bool:
    if not csrf_token_from_header:
        return False

    async with redis.pipeline(transaction=False) as pipe:
        pipe.get(_session_key(session_id))
        pipe.get(_csrf_key(session_id))
        session_raw, csrf_raw = await pipe.execute()

    if not session_raw or not csrf_raw:
        return False

    if isinstance(csrf_raw, bytes):
        csrf_raw = csrf_raw.decode()

    return secrets.compare_digest(csrf_raw, csrf_token_from_header)
