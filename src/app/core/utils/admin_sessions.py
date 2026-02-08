from __future__ import annotations

import hashlib
import json
import logging
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, NotRequired, TypedDict

from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadData, URLSafeSerializer
from redis.asyncio import Redis

from ..config import settings

logger = logging.getLogger(__name__)

__all__ = [
    "SESSION_COOKIE_NAME",
    "CSRF_COOKIE_NAME",
    "SAFE_HTTP_METHODS",
    "SessionData",
    "SessionInfo",
    "SessionEvent",
    "SessionConfiguration",
    "SessionManager",
    "create_session_manager",
    "set_admin_cookies",
    "clear_admin_cookies",
]

SESSION_COOKIE_NAME: Final[str] = "admin_session"
CSRF_COOKIE_NAME: Final[str] = "admin_csrf"
SAFE_HTTP_METHODS: Final[frozenset[str]] = frozenset({"GET", "HEAD", "OPTIONS"})

SESSION_SIGNING_SALT: Final[str] = "admin-session-v2"

SESSION_IDENTIFIER_TOKEN_BYTES: Final[int] = 32
CSRF_TOKEN_BYTES: Final[int] = 32

SESSION_REDIS_KEY_PREFIX: Final[str] = "admin:session:"
CSRF_REDIS_KEY_PREFIX: Final[str] = "admin:csrf:"
USER_SESSIONS_REDIS_KEY_PREFIX: Final[str] = "admin:user_sessions:"

ADMIN_COOKIE_PATH: Final[str] = "/api/v1/admin"
ADMIN_COOKIE_SAMESITE: Final[str] = "lax"

MAX_METADATA_KEY_LENGTH: Final[int] = 100
MAX_METADATA_VALUE_SIZE: Final[int] = 1024

SAFE_DETAIL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "evicted_sessions",
        "reason",
        "ip_address",
        "attempt_count",
    }
)

_EVICT_AND_INSERT_LUA: Final[str] = r"""
local session_key = KEYS[1]
local csrf_key = KEYS[2]
local zset_key = KEYS[3]

local session_payload = ARGV[1]
local csrf_token = ARGV[2]
local session_ex = tonumber(ARGV[3])
local zset_abs_ex = tonumber(ARGV[4])
local max_sessions = tonumber(ARGV[5])
local created_at = tonumber(ARGV[6])
local session_id = ARGV[7]
local session_prefix = ARGV[8]
local csrf_prefix = ARGV[9]

local count = redis.call('ZCARD', zset_key)
local evicted = 0

if count >= max_sessions then
  local to_evict = (count - max_sessions) + 1
  local sids = redis.call('ZRANGE', zset_key, 0, to_evict - 1)
  for i = 1, #sids do
    local sid = sids[i]
    redis.call('DEL', session_prefix .. sid)
    redis.call('DEL', csrf_prefix .. sid)
    redis.call('ZREM', zset_key, sid)
    evicted = evicted + 1
  end
end

redis.call('SET', session_key, session_payload, 'EX', session_ex)
redis.call('SET', csrf_key, csrf_token, 'EX', session_ex)
redis.call('ZADD', zset_key, created_at, session_id)
redis.call('EXPIRE', zset_key, zset_abs_ex)

return evicted
"""


class SessionData(TypedDict):
    user_id: int
    created_at_timestamp_seconds: int
    username: NotRequired[str]
    role: NotRequired[str]
    request_fingerprint: NotRequired[str]


class SessionInfo(SessionData):
    session_id: str


class SessionEvent(StrEnum):
    SESSION_CREATED = "session.created"
    SESSION_DELETED = "session.deleted"
    SESSION_VALIDATED = "session.validated"
    SESSION_REFRESHED = "session.refreshed"
    SESSION_EXPIRED = "session.expired"
    INVALID_SIGNATURE = "session.invalid_signature"
    MALFORMED_SESSION = "session.malformed"
    CSRF_FAILED = "session.csrf_failed"
    SESSION_BINDING_MISMATCH = "session.binding_mismatch"
    MAXIMUM_SESSIONS_EVICTED = "session.max_sessions_evicted"
    SESSION_ROTATED = "session.rotated"
    LOGIN_SUCCESS = "admin.login_success"
    LOGIN_FAILED = "admin.login_failed"
    LOGOUT = "admin.logout"


@dataclass(frozen=True)
class SessionConfiguration:
    sliding_time_to_live_seconds: int
    absolute_time_to_live_seconds: int
    enable_session_binding: bool = True
    maximum_sessions_per_user: int = 3
    cookie_secure: bool = True


def set_admin_cookies(
    response: Response,
    *,
    signed_session: str,
    csrf_token: str,
    cookie_secure: bool,
) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=signed_session,
        httponly=True,
        secure=cookie_secure,
        samesite=ADMIN_COOKIE_SAMESITE,
        path=ADMIN_COOKIE_PATH,
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=cookie_secure,
        samesite=ADMIN_COOKIE_SAMESITE,
        path=ADMIN_COOKIE_PATH,
    )


def clear_admin_cookies(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path=ADMIN_COOKIE_PATH)
    response.delete_cookie(key=CSRF_COOKIE_NAME, path=ADMIN_COOKIE_PATH)


def current_utc_timestamp_seconds() -> int:
    return int(datetime.now(UTC).timestamp())


def validate_session_configuration(session_configuration: SessionConfiguration) -> None:
    if session_configuration.sliding_time_to_live_seconds <= 0:
        raise ValueError("sliding_time_to_live_seconds must be positive")
    if session_configuration.absolute_time_to_live_seconds <= 0:
        raise ValueError("absolute_time_to_live_seconds must be positive")
    if session_configuration.sliding_time_to_live_seconds > session_configuration.absolute_time_to_live_seconds:
        raise ValueError("sliding_time_to_live_seconds must be <= absolute_time_to_live_seconds")
    if session_configuration.maximum_sessions_per_user < 1:
        raise ValueError("maximum_sessions_per_user must be at least 1")


def validate_user_id(user_id: int) -> None:
    if not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("user_id must be a positive integer")


def json_serializer(obj: Any) -> str:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def validate_metadata(metadata: dict[str, Any]) -> None:
    reserved_keys = {
        "user_id",
        "created_at_timestamp_seconds",
        "request_fingerprint",
        "session_id",
    }

    if any(key in reserved_keys for key in metadata.keys()):
        raise ValueError(f"metadata contains reserved keys: {sorted(reserved_keys)}")

    for key, value in metadata.items():
        if not isinstance(key, str) or len(key) > MAX_METADATA_KEY_LENGTH:
            raise ValueError(f"Invalid metadata key: {key}")

        try:
            serialized_size = len(json.dumps(value, separators=(",", ":"), default=json_serializer))
        except TypeError as e:
            raise ValueError(f"Metadata value not JSON-serializable for key: {key}") from e

        if serialized_size > MAX_METADATA_VALUE_SIZE:
            raise ValueError(f"Metadata value too large for key: {key}")


def session_redis_key(session_id: str) -> str:
    return f"{SESSION_REDIS_KEY_PREFIX}{session_id}"


def csrf_redis_key(session_id: str) -> str:
    return f"{CSRF_REDIS_KEY_PREFIX}{session_id}"


def user_sessions_redis_key(user_id: int) -> str:
    return f"{USER_SESSIONS_REDIS_KEY_PREFIX}{user_id}"


def compute_request_fingerprint(request: Request) -> str:
    user_agent_header = request.headers.get("user-agent", "")
    accept_language_header = request.headers.get("accept-language", "")
    fingerprint_input_bytes = f"{user_agent_header}\x00{accept_language_header}".encode("utf-8", errors="ignore")
    return hashlib.sha256(fingerprint_input_bytes).hexdigest()


def effective_time_to_live_seconds(
    created_at_timestamp_seconds: int,
    session_configuration: SessionConfiguration,
) -> int:
    now_timestamp_seconds = current_utc_timestamp_seconds()
    session_age_seconds = max(0, now_timestamp_seconds - created_at_timestamp_seconds)
    remaining_absolute_seconds = session_configuration.absolute_time_to_live_seconds - session_age_seconds
    if remaining_absolute_seconds <= 0:
        return 0
    return min(session_configuration.sliding_time_to_live_seconds, remaining_absolute_seconds)


class SessionManager:
    def __init__(
        self,
        redis_client: Redis,
        session_configuration: SessionConfiguration,
        signing_secret: str,
    ) -> None:
        validate_session_configuration(session_configuration)
        self._redis_client = redis_client
        self._session_configuration = session_configuration
        self._serializer = URLSafeSerializer(signing_secret, salt=SESSION_SIGNING_SALT)

    @property
    def cookie_secure(self) -> bool:
        return self._session_configuration.cookie_secure

    def sign_session_id(self, session_id: str) -> str:
        return self._serializer.dumps({"session_id": session_id})

    def unsign_session_id(self, signed_session_cookie_value: str) -> str | None:
        try:
            payload = self._serializer.loads(signed_session_cookie_value)
        except BadData:
            return None
        if not isinstance(payload, dict):
            return None
        session_id_value = payload.get("session_id")
        return session_id_value if isinstance(session_id_value, str) else None

    def log_event(
        self,
        event: SessionEvent,
        *,
        session_id: str | None = None,
        user_id: int | None = None,
        details: dict[str, Any] | None = None,
        log_level: int = logging.INFO,
    ) -> None:
        log_payload: dict[str, Any] = {
            "event": event.value,
            "timestamp_seconds": current_utc_timestamp_seconds(),
        }
        if session_id is not None:
            log_payload["session_id_prefix"] = session_id[:8]
        if user_id is not None:
            log_payload["user_id"] = user_id
        if details:
            safe_details = {k: v for k, v in details.items() if k in SAFE_DETAIL_KEYS}
            log_payload.update(safe_details)
        logger.log(log_level, event.value, extra=log_payload)

    async def create_session(
        self,
        *,
        request: Request,
        user_id: int,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, str, int]:
        validate_user_id(user_id)
        if metadata:
            validate_metadata(metadata)

        session_id = secrets.token_urlsafe(SESSION_IDENTIFIER_TOKEN_BYTES)
        csrf_token = secrets.token_urlsafe(CSRF_TOKEN_BYTES)
        created_at_timestamp_seconds = current_utc_timestamp_seconds()

        session_payload: dict[str, Any] = {
            "user_id": user_id,
            "created_at_timestamp_seconds": created_at_timestamp_seconds,
        }

        if self._session_configuration.enable_session_binding:
            session_payload["request_fingerprint"] = compute_request_fingerprint(request)

        if metadata:
            session_payload.update(metadata)

        serialized_session_payload = json.dumps(
            session_payload,
            separators=(",", ":"),
            default=json_serializer,
        )

        expiration_seconds = effective_time_to_live_seconds(
            created_at_timestamp_seconds,
            self._session_configuration,
        )
        if expiration_seconds <= 0:
            raise RuntimeError("Session configuration produced a non-positive expiration_seconds")

        user_sessions_key = user_sessions_redis_key(user_id)

        try:
            evicted = await self._redis_client.eval(
                _EVICT_AND_INSERT_LUA,
                3,
                session_redis_key(session_id),
                csrf_redis_key(session_id),
                user_sessions_key,
                serialized_session_payload,
                csrf_token,
                str(expiration_seconds),
                str(self._session_configuration.absolute_time_to_live_seconds),
                str(self._session_configuration.maximum_sessions_per_user),
                str(created_at_timestamp_seconds),
                session_id,
                SESSION_REDIS_KEY_PREFIX,
                CSRF_REDIS_KEY_PREFIX,
            )
        except Exception:
            try:
                async with self._redis_client.pipeline(transaction=True) as p:
                    p.delete(session_redis_key(session_id))
                    p.delete(csrf_redis_key(session_id))
                    p.zrem(user_sessions_key, session_id)
                    await p.execute()
            except Exception:
                pass
            raise

        if int(evicted) > 0:
            self.log_event(
                SessionEvent.MAXIMUM_SESSIONS_EVICTED,
                user_id=user_id,
                details={"evicted_sessions": int(evicted)},
                log_level=logging.INFO,
            )

        self.log_event(SessionEvent.SESSION_CREATED, session_id=session_id, user_id=user_id)
        return session_id, csrf_token, int(evicted)

    async def read_session(self, *, session_id: str) -> SessionData | None:
        raw_value = await self._redis_client.get(session_redis_key(session_id))
        if not raw_value:
            return None

        if isinstance(raw_value, bytes):
            raw_value = raw_value.decode()

        try:
            decoded_value = json.loads(raw_value)
        except json.JSONDecodeError:
            self.log_event(SessionEvent.MALFORMED_SESSION, session_id=session_id, log_level=logging.WARNING)
            return None

        if not isinstance(decoded_value, dict):
            self.log_event(SessionEvent.MALFORMED_SESSION, session_id=session_id, log_level=logging.WARNING)
            return None

        if "user_id" not in decoded_value or "created_at_timestamp_seconds" not in decoded_value:
            self.log_event(SessionEvent.MALFORMED_SESSION, session_id=session_id, log_level=logging.WARNING)
            return None

        try:
            decoded_value["user_id"] = int(decoded_value["user_id"])
            decoded_value["created_at_timestamp_seconds"] = int(decoded_value["created_at_timestamp_seconds"])
        except (TypeError, ValueError):
            self.log_event(SessionEvent.MALFORMED_SESSION, session_id=session_id, log_level=logging.WARNING)
            return None

        return decoded_value  # type: ignore[return-value]

    async def refresh_and_read_session(self, *, session_id: str) -> SessionData | None:
        existing_session = await self.read_session(session_id=session_id)
        if not existing_session:
            await self.delete_session(session_id=session_id)
            self.log_event(SessionEvent.SESSION_EXPIRED, session_id=session_id, log_level=logging.INFO)
            return None

        expiration_seconds = effective_time_to_live_seconds(
            existing_session["created_at_timestamp_seconds"],
            self._session_configuration,
        )
        if expiration_seconds <= 0:
            await self.delete_session(session_id=session_id, user_id=existing_session["user_id"])
            self.log_event(SessionEvent.SESSION_EXPIRED, session_id=session_id, user_id=existing_session["user_id"])
            return None

        async with self._redis_client.pipeline(transaction=True) as p:
            p.expire(session_redis_key(session_id), expiration_seconds)
            p.expire(csrf_redis_key(session_id), expiration_seconds)
            await p.execute()

        self.log_event(SessionEvent.SESSION_REFRESHED, session_id=session_id, user_id=existing_session["user_id"])
        return existing_session

    async def delete_session(self, *, session_id: str, user_id: int | None = None) -> None:
        resolved_user_id = user_id
        if resolved_user_id is None:
            existing_session = await self.read_session(session_id=session_id)
            resolved_user_id = existing_session["user_id"] if existing_session else None

        async with self._redis_client.pipeline(transaction=True) as p:
            p.delete(session_redis_key(session_id))
            p.delete(csrf_redis_key(session_id))
            if resolved_user_id is not None:
                p.zrem(user_sessions_redis_key(resolved_user_id), session_id)
            await p.execute()

        self.log_event(SessionEvent.SESSION_DELETED, session_id=session_id, user_id=resolved_user_id)

    async def validate_csrf(self, *, session_id: str, csrf_token_from_header: str | None) -> bool:
        if not csrf_token_from_header:
            return False

        session_value, csrf_value = await self._redis_client.mget(
            [
                session_redis_key(session_id),
                csrf_redis_key(session_id),
            ]
        )
        if not session_value or not csrf_value:
            return False

        if isinstance(csrf_value, bytes):
            csrf_value = csrf_value.decode()

        return secrets.compare_digest(str(csrf_value), csrf_token_from_header)

    async def get_session(self, *, request: Request) -> SessionInfo | None:
        signed_cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
        if not signed_cookie_value:
            return None

        session_id = self.unsign_session_id(signed_cookie_value)
        if not session_id:
            self.log_event(SessionEvent.INVALID_SIGNATURE, log_level=logging.INFO)
            return None

        existing_session = await self.refresh_and_read_session(session_id=session_id)
        if not existing_session:
            return None

        if self._session_configuration.enable_session_binding:
            stored_fingerprint = existing_session.get("request_fingerprint")
            current_fingerprint = compute_request_fingerprint(request)
            if stored_fingerprint and stored_fingerprint != current_fingerprint:
                self.log_event(
                    SessionEvent.SESSION_BINDING_MISMATCH,
                    session_id=session_id,
                    user_id=existing_session["user_id"],
                    log_level=logging.WARNING,
                )
                await self.delete_session(session_id=session_id, user_id=existing_session["user_id"])
                return None

        session_info: SessionInfo = {**existing_session, "session_id": session_id}  # type: ignore[assignment]
        self.log_event(SessionEvent.SESSION_VALIDATED, session_id=session_id, user_id=existing_session["user_id"])
        return session_info

    async def require_session(self, *, request: Request) -> SessionInfo:
        session_info = await self.get_session(request=request)
        if not session_info:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        return session_info

    async def enforce_csrf(self, *, request: Request) -> SessionInfo:
        if request.method in SAFE_HTTP_METHODS:
            return await self.require_session(request=request)

        signed_cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
        if not signed_cookie_value:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        session_id = self.unsign_session_id(signed_cookie_value)
        if not session_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        csrf_header_value = request.headers.get("x-csrf-token")
        valid = await self.validate_csrf(session_id=session_id, csrf_token_from_header=csrf_header_value)
        if not valid:
            self.log_event(SessionEvent.CSRF_FAILED, session_id=session_id, log_level=logging.WARNING)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")

        session_data = await self.refresh_and_read_session(session_id=session_id)
        if not session_data:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        if self._session_configuration.enable_session_binding:
            stored_fingerprint = session_data.get("request_fingerprint")
            current_fingerprint = compute_request_fingerprint(request)
            if stored_fingerprint and stored_fingerprint != current_fingerprint:
                self.log_event(
                    SessionEvent.SESSION_BINDING_MISMATCH,
                    session_id=session_id,
                    user_id=session_data["user_id"],
                    log_level=logging.WARNING,
                )
                await self.delete_session(session_id=session_id, user_id=session_data["user_id"])
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        return {**session_data, "session_id": session_id}  # type: ignore[return-value]

    async def delete_all_user_sessions(self, *, user_id: int) -> int:
        validate_user_id(user_id)
        zset_key = user_sessions_redis_key(user_id)

        raw_sids: Sequence[bytes | str] = await self._redis_client.zrange(zset_key, 0, -1)
        if not raw_sids:
            await self._redis_client.delete(zset_key)
            return 0

        sids: list[str] = [
            (sid.decode() if isinstance(sid, bytes) else sid)
            for sid in raw_sids
            if (sid.decode() if isinstance(sid, bytes) else sid)
        ]

        if not sids:
            await self._redis_client.delete(zset_key)
            return 0

        keys: list[str] = [zset_key]
        for sid in sids:
            keys.append(session_redis_key(sid))
            keys.append(csrf_redis_key(sid))

        async with self._redis_client.pipeline(transaction=True) as p:
            p.delete(*keys)
            await p.execute()

        self.log_event(SessionEvent.LOGOUT, user_id=user_id, log_level=logging.INFO)
        return len(sids)


def create_session_manager(
    *,
    redis_client: Redis,
    sliding_time_to_live_seconds: int,
    absolute_time_to_live_seconds: int,
    enable_session_binding: bool = True,
    maximum_sessions_per_user: int = 3,
    cookie_secure: bool = True,
) -> SessionManager:
    signing_secret = settings.ADMIN_SESSION_SIGNING_SECRET.get_secret_value()

    session_configuration = SessionConfiguration(
        sliding_time_to_live_seconds=sliding_time_to_live_seconds,
        absolute_time_to_live_seconds=absolute_time_to_live_seconds,
        enable_session_binding=enable_session_binding,
        maximum_sessions_per_user=maximum_sessions_per_user,
        cookie_secure=cookie_secure,
    )
    return SessionManager(
        redis_client=redis_client,
        session_configuration=session_configuration,
        signing_secret=signing_secret,
    )
