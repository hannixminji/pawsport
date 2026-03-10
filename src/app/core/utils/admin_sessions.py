import asyncio
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, NotRequired, TypedDict

from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadData, SignatureExpired, URLSafeTimedSerializer
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

MAX_METADATA_KEY_LENGTH: Final[int] = 100
MAX_METADATA_VALUE_SIZE: Final[int] = 1_024

SAFE_LOG_DETAIL_KEYS: Final[frozenset[str]] = frozenset(
    {"evicted_sessions", "reason", "ip_address", "attempt_count", "rotated"}
)

_METADATA_RESERVED_KEYS: Final[frozenset[str]] = frozenset(
    {"user_id", "created_at_timestamp_seconds", "request_fingerprint", "session_id"}
)

_EVICT_AND_INSERT_LUA: Final[str] = r"""
local session_key  = KEYS[1]
local csrf_key     = KEYS[2]
local zset_key     = KEYS[3]

local session_payload  = ARGV[1]
local csrf_token       = ARGV[2]
local session_ex       = tonumber(ARGV[3])
local zset_abs_ex      = tonumber(ARGV[4])
local max_sessions     = tonumber(ARGV[5])
local created_at       = tonumber(ARGV[6])
local session_id       = ARGV[7]
local session_prefix   = ARGV[8]
local csrf_prefix      = ARGV[9]

local all_sids = redis.call('ZRANGE', zset_key, 0, -1)
for i = 1, #all_sids do
  if redis.call('EXISTS', session_prefix .. all_sids[i]) == 0 then
    redis.call('ZREM', zset_key, all_sids[i])
  end
end

local count   = redis.call('ZCARD', zset_key)
local evicted = 0

if count >= max_sessions then
  local to_evict = (count - max_sessions) + 1
  local sids = redis.call('ZRANGE', zset_key, 0, to_evict - 1)
  for i = 1, #sids do
    local sid = sids[i]
    redis.call('DEL', session_prefix .. sid)
    redis.call('DEL', csrf_prefix  .. sid)
    redis.call('ZREM', zset_key, sid)
    evicted = evicted + 1
  end
end

redis.call('SET',    session_key, session_payload, 'EX', session_ex)
redis.call('SET',    csrf_key,    csrf_token,      'EX', session_ex)
redis.call('ZADD',   zset_key, created_at, session_id)
redis.call('EXPIRE', zset_key, zset_abs_ex)

return evicted
"""

_REFRESH_AND_READ_LUA: Final[str] = r"""
local session_val = redis.call('GET', KEYS[1])
if not session_val then return false end

local created_at_str = session_val:match('"created_at_timestamp_seconds":(%d+)')
if not created_at_str then return false end

local created_at    = tonumber(created_at_str)
local now           = tonumber(ARGV[1])
local sliding_ttl   = tonumber(ARGV[2])
local absolute_ttl  = tonumber(ARGV[3])

local age               = now - created_at
local remaining_abs     = absolute_ttl - age
if remaining_abs <= 0 then return false end

local effective_ttl = math.min(sliding_ttl, remaining_abs)
local csrf_val      = redis.call('GET', KEYS[2])

redis.call('EXPIRE', KEYS[1], effective_ttl)
if csrf_val then redis.call('EXPIRE', KEYS[2], effective_ttl) end

return {session_val, csrf_val or '', tostring(effective_ttl)}
"""

_VALIDATE_CSRF_AND_REFRESH_LUA: Final[str] = r"""
local session_val = redis.call('GET', KEYS[1])
if not session_val then return false end

local csrf_val = redis.call('GET', KEYS[2])
if not csrf_val then return false end
if csrf_val ~= ARGV[1] then return false end

local created_at_str = session_val:match('"created_at_timestamp_seconds":(%d+)')
if not created_at_str then return false end

local created_at   = tonumber(created_at_str)
local now          = tonumber(ARGV[2])
local sliding_ttl  = tonumber(ARGV[3])
local absolute_ttl = tonumber(ARGV[4])

local age           = now - created_at
local remaining_abs = absolute_ttl - age
if remaining_abs <= 0 then return false end

local effective_ttl = math.min(sliding_ttl, remaining_abs)
redis.call('EXPIRE', KEYS[1], effective_ttl)
redis.call('EXPIRE', KEYS[2], effective_ttl)

return {session_val, tostring(effective_ttl)}
"""

_ROTATE_SESSION_LUA: Final[str] = r"""
local exists = redis.call('EXISTS', KEYS[1])
if exists == 0 then return 0 end

redis.call('DEL',  KEYS[1], KEYS[2])
redis.call('ZREM', KEYS[5], ARGV[4])

local ex = tonumber(ARGV[3])
redis.call('SET',  KEYS[3], ARGV[1], 'EX', ex)
redis.call('SET',  KEYS[4], ARGV[2], 'EX', ex)
redis.call('ZADD', KEYS[5], tonumber(ARGV[6]), ARGV[5])
redis.call('EXPIRE', KEYS[5], ex)

return 1
"""

_DELETE_SESSION_LUA: Final[str] = r"""
local session_val = redis.call('GET', KEYS[1])
if not session_val then
  redis.call('DEL', KEYS[2])
  return 0
end

local user_id_str = session_val:match('"user_id":(%d+)')
redis.call('DEL', KEYS[1], KEYS[2])

if user_id_str and ARGV[1] ~= '' then
  redis.call('ZREM', ARGV[1] .. user_id_str, KEYS[3])
end

return 1
"""

_DELETE_ALL_SESSIONS_LUA: Final[str] = r"""
local zset_key = KEYS[1]
local sids = redis.call('ZRANGE', zset_key, 0, -1)
local count = #sids
if count == 0 then
  redis.call('DEL', zset_key)
  return 0
end
local keys_to_del = {zset_key}
for i = 1, count do
  table.insert(keys_to_del, ARGV[1] .. sids[i])
  table.insert(keys_to_del, ARGV[2] .. sids[i])
end
redis.call('DEL', unpack(keys_to_del))
return count
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
    SESSION_ROTATED = "session.rotated"
    INVALID_SIGNATURE = "session.invalid_signature"
    MALFORMED_SESSION = "session.malformed"
    CSRF_FAILED = "session.csrf_failed"
    SESSION_BINDING_MISMATCH = "session.binding_mismatch"
    MAXIMUM_SESSIONS_EVICTED = "session.max_sessions_evicted"
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
    max_age: int,
) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=signed_session,
        httponly=True,
        secure=cookie_secure,
        samesite=settings.ADMIN_SESSION_COOKIE_SAMESITE,
        path=settings.ADMIN_SESSION_COOKIE_PATH,
        max_age=max_age,
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=cookie_secure,
        samesite=settings.ADMIN_SESSION_COOKIE_SAMESITE,
        path=settings.ADMIN_SESSION_COOKIE_PATH,
        max_age=max_age,
    )


def clear_admin_cookies(response: Response, *, cookie_secure: bool) -> None:
    for name in (SESSION_COOKIE_NAME, CSRF_COOKIE_NAME):
        response.delete_cookie(
            key=name,
            path=settings.ADMIN_SESSION_COOKIE_PATH,
            secure=cookie_secure,
            samesite=settings.ADMIN_SESSION_COOKIE_SAMESITE,
        )


def _now_seconds() -> int:
    return int(datetime.now(UTC).timestamp())


def _validate_session_configuration(cfg: SessionConfiguration) -> None:
    if cfg.sliding_time_to_live_seconds <= 0:
        raise ValueError("sliding_time_to_live_seconds must be positive")
    if cfg.absolute_time_to_live_seconds <= 0:
        raise ValueError("absolute_time_to_live_seconds must be positive")
    if cfg.sliding_time_to_live_seconds > cfg.absolute_time_to_live_seconds:
        raise ValueError("sliding_time_to_live_seconds must be <= absolute_time_to_live_seconds")
    if cfg.maximum_sessions_per_user < 1:
        raise ValueError("maximum_sessions_per_user must be at least 1")


def _validate_user_id(user_id: int) -> None:
    if not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("user_id must be a positive integer")


def _json_default(obj: Any) -> str:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _validate_metadata(metadata: dict[str, Any]) -> None:
    if any(key in _METADATA_RESERVED_KEYS for key in metadata):
        raise ValueError(f"metadata contains reserved keys: {sorted(_METADATA_RESERVED_KEYS)}")

    for key, value in metadata.items():
        if not isinstance(key, str) or len(key) > MAX_METADATA_KEY_LENGTH:
            raise ValueError(f"Invalid metadata key: {key!r}")

        try:
            serialized_size = len(
                json.dumps(value, separators=(",", ":"), default=_json_default)
            )
        except TypeError as exc:
            raise ValueError(f"Metadata value not JSON-serialisable for key {key!r}") from exc

        if serialized_size > MAX_METADATA_VALUE_SIZE:
            raise ValueError(f"Metadata value too large for key {key!r}")


def _session_key(session_id: str) -> str:
    return f"{SESSION_REDIS_KEY_PREFIX}{session_id}"


def _csrf_key(session_id: str) -> str:
    return f"{CSRF_REDIS_KEY_PREFIX}{session_id}"


def _user_sessions_key(user_id: int) -> str:
    return f"{USER_SESSIONS_REDIS_KEY_PREFIX}{user_id}"


def _fingerprint(request: Request) -> str:
    raw = (
        f"{request.headers.get('user-agent', '')}\x00"
        f"{request.headers.get('accept-language', '')}"
    ).encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()


def _decode_bytes(value: bytes | str | None) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else value


def _parse_session_payload(raw: str | bytes, session_id: str, log_fn: Any) -> SessionData | None:
    text = _decode_bytes(raw) if isinstance(raw, bytes) else raw  # type: ignore[arg-type]
    if not text:
        return None
    try:
        decoded: Any = json.loads(text)
    except json.JSONDecodeError:
        log_fn(SessionEvent.MALFORMED_SESSION, session_id=session_id, log_level=logging.WARNING)
        return None

    if not isinstance(decoded, dict):
        log_fn(SessionEvent.MALFORMED_SESSION, session_id=session_id, log_level=logging.WARNING)
        return None

    if "user_id" not in decoded or "created_at_timestamp_seconds" not in decoded:
        log_fn(SessionEvent.MALFORMED_SESSION, session_id=session_id, log_level=logging.WARNING)
        return None

    try:
        decoded["user_id"] = int(decoded["user_id"])
        decoded["created_at_timestamp_seconds"] = int(decoded["created_at_timestamp_seconds"])
    except (TypeError, ValueError):
        log_fn(SessionEvent.MALFORMED_SESSION, session_id=session_id, log_level=logging.WARNING)
        return None

    return decoded  # type: ignore[return-value]


class SessionManager:
    __slots__ = ("_redis", "_cfg", "_serializer")

    def __init__(
        self,
        redis_client: Redis,
        session_configuration: SessionConfiguration,
        signing_secret: str,
    ) -> None:
        _validate_session_configuration(session_configuration)
        self._redis = redis_client
        self._cfg = session_configuration
        self._serializer: URLSafeTimedSerializer = URLSafeTimedSerializer(
            signing_secret, salt=SESSION_SIGNING_SALT
        )

    @property
    def cookie_secure(self) -> bool:
        return self._cfg.cookie_secure

    def sign_session_id(self, session_id: str) -> str:
        return self._serializer.dumps({"session_id": session_id})

    def unsign_session_id(self, signed_value: str) -> str | None:
        try:
            payload: Any = self._serializer.loads(
                signed_value,
                max_age=self._cfg.absolute_time_to_live_seconds,
            )
        except (BadData, SignatureExpired):
            return None
        if not isinstance(payload, dict):
            return None
        sid = payload.get("session_id")
        return sid if isinstance(sid, str) else None

    def log_event(
        self,
        event: SessionEvent,
        *,
        session_id: str | None = None,
        user_id: int | None = None,
        details: dict[str, Any] | None = None,
        log_level: int = logging.INFO,
    ) -> None:
        payload: dict[str, Any] = {
            "event": event.value,
            "timestamp_seconds": _now_seconds(),
        }
        if session_id is not None:
            payload["session_id_prefix"] = session_id[:8]
        if user_id is not None:
            payload["user_id"] = user_id
        if details:
            payload.update(
                {k: v for k, v in details.items() if k in SAFE_LOG_DETAIL_KEYS}
            )
        logger.log(log_level, event.value, extra=payload)

    async def create_session(
        self,
        *,
        request: Request,
        user_id: int,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, str, int]:
        _validate_user_id(user_id)
        if metadata:
            _validate_metadata(metadata)

        session_id = secrets.token_urlsafe(SESSION_IDENTIFIER_TOKEN_BYTES)
        csrf_token = secrets.token_urlsafe(CSRF_TOKEN_BYTES)
        created_at = _now_seconds()

        payload: dict[str, Any] = {
            "user_id": user_id,
            "created_at_timestamp_seconds": created_at,
        }
        if self._cfg.enable_session_binding:
            payload["request_fingerprint"] = _fingerprint(request)
        if metadata:
            payload.update(metadata)

        serialized = json.dumps(payload, separators=(",", ":"), default=_json_default)

        expiration_seconds = self._effective_ttl(created_at)
        if expiration_seconds <= 0:
            raise RuntimeError("Session configuration produced a non-positive expiration_seconds")

        user_key = _user_sessions_key(user_id)
        evicted = await self._redis.eval(
            _EVICT_AND_INSERT_LUA,
            3,
            _session_key(session_id),
            _csrf_key(session_id),
            user_key,
            serialized,
            csrf_token,
            str(expiration_seconds),
            str(self._cfg.absolute_time_to_live_seconds),
            str(self._cfg.maximum_sessions_per_user),
            str(created_at),
            session_id,
            SESSION_REDIS_KEY_PREFIX,
            CSRF_REDIS_KEY_PREFIX,
        )

        evicted_count = int(evicted)
        if evicted_count > 0:
            self.log_event(
                SessionEvent.MAXIMUM_SESSIONS_EVICTED,
                user_id=user_id,
                details={"evicted_sessions": evicted_count},
            )

        self.log_event(SessionEvent.SESSION_CREATED, session_id=session_id, user_id=user_id)
        return session_id, csrf_token, evicted_count

    async def rotate_session(
        self,
        *,
        request: Request,
        session_id: str,
        user_id: int,
        created_at_timestamp_seconds: int,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, str] | None:
        if metadata:
            _validate_metadata(metadata)

        new_session_id = secrets.token_urlsafe(SESSION_IDENTIFIER_TOKEN_BYTES)
        new_csrf_token = secrets.token_urlsafe(CSRF_TOKEN_BYTES)

        expiration_seconds = self._effective_ttl(created_at_timestamp_seconds)
        if expiration_seconds <= 0:
            return None

        new_payload: dict[str, Any] = {
            "user_id": user_id,
            "created_at_timestamp_seconds": created_at_timestamp_seconds,
        }
        if self._cfg.enable_session_binding:
            new_payload["request_fingerprint"] = _fingerprint(request)
        if metadata:
            new_payload.update(metadata)

        serialized = json.dumps(new_payload, separators=(",", ":"), default=_json_default)
        user_key = _user_sessions_key(user_id)

        result = await self._redis.eval(
            _ROTATE_SESSION_LUA,
            5,
            _session_key(session_id),
            _csrf_key(session_id),
            _session_key(new_session_id),
            _csrf_key(new_session_id),
            user_key,
            serialized,
            new_csrf_token,
            str(expiration_seconds),
            session_id,
            new_session_id,
            str(created_at_timestamp_seconds),
        )

        if not result:
            return None

        self.log_event(
            SessionEvent.SESSION_ROTATED,
            session_id=new_session_id,
            user_id=user_id,
            details={"rotated": True},
        )
        return new_session_id, new_csrf_token

    async def read_session(self, *, session_id: str) -> SessionData | None:
        raw = await self._redis.get(_session_key(session_id))
        if not raw:
            return None
        return _parse_session_payload(raw, session_id, self.log_event)

    async def refresh_and_read_session(self, *, session_id: str) -> SessionData | None:
        now = _now_seconds()
        result: Any = await self._redis.eval(
            _REFRESH_AND_READ_LUA,
            2,
            _session_key(session_id),
            _csrf_key(session_id),
            str(now),
            str(self._cfg.sliding_time_to_live_seconds),
            str(self._cfg.absolute_time_to_live_seconds),
        )

        if not result:
            self.log_event(SessionEvent.SESSION_EXPIRED, session_id=session_id)
            await self.delete_session(session_id=session_id)
            return None

        session_json, _csrf_raw, _ttl = result
        session_data = _parse_session_payload(session_json, session_id, self.log_event)
        if session_data is None:
            return None

        self.log_event(
            SessionEvent.SESSION_REFRESHED,
            session_id=session_id,
            user_id=session_data["user_id"],
        )
        return session_data

    async def delete_session(self, *, session_id: str, user_id: int | None = None) -> None:
        if user_id is not None:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.delete(_session_key(session_id))
                pipe.delete(_csrf_key(session_id))
                pipe.zrem(_user_sessions_key(user_id), session_id)
                await pipe.execute()
        else:
            await self._redis.eval(
                _DELETE_SESSION_LUA,
                3,
                _session_key(session_id),
                _csrf_key(session_id),
                session_id,
                USER_SESSIONS_REDIS_KEY_PREFIX,
            )

        self.log_event(
            SessionEvent.SESSION_DELETED,
            session_id=session_id,
            user_id=user_id,
        )

    async def delete_all_user_sessions(self, *, user_id: int) -> int:
        _validate_user_id(user_id)
        count: int = await self._redis.eval(
            _DELETE_ALL_SESSIONS_LUA,
            1,
            _user_sessions_key(user_id),
            SESSION_REDIS_KEY_PREFIX,
            CSRF_REDIS_KEY_PREFIX,
        )
        self.log_event(SessionEvent.LOGOUT, user_id=user_id)
        return int(count)

    async def validate_csrf(self, *, session_id: str, csrf_token_from_header: str | None) -> bool:
        if not csrf_token_from_header:
            return False

        session_val, csrf_val = await self._redis.mget(
            [_session_key(session_id), _csrf_key(session_id)]
        )
        if not session_val or not csrf_val:
            return False

        stored_csrf = _decode_bytes(csrf_val)
        return secrets.compare_digest(stored_csrf or "", csrf_token_from_header)

    async def get_session(self, *, request: Request) -> SessionInfo | None:
        signed_cookie = request.cookies.get(SESSION_COOKIE_NAME)
        if not signed_cookie:
            return None

        session_id = self.unsign_session_id(signed_cookie)
        if not session_id:
            self.log_event(SessionEvent.INVALID_SIGNATURE)
            return None

        session_data = await self.refresh_and_read_session(session_id=session_id)
        if not session_data:
            return None

        if not self._check_fingerprint(request, session_id, session_data):
            return None

        self.log_event(
            SessionEvent.SESSION_VALIDATED,
            session_id=session_id,
            user_id=session_data["user_id"],
        )
        return {**session_data, "session_id": session_id}

    async def require_session(self, *, request: Request) -> SessionInfo:
        session_info = await self.get_session(request=request)
        if not session_info:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )
        return session_info

    async def enforce_csrf(self, *, request: Request) -> SessionInfo:
        if request.method in SAFE_HTTP_METHODS:
            return await self.require_session(request=request)

        signed_cookie = request.cookies.get(SESSION_COOKIE_NAME)
        if not signed_cookie:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        session_id = self.unsign_session_id(signed_cookie)
        if not session_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        csrf_header = request.headers.get("x-csrf-token")
        if not csrf_header:
            self.log_event(SessionEvent.CSRF_FAILED, session_id=session_id, log_level=logging.WARNING)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")

        now = _now_seconds()
        result: Any = await self._redis.eval(
            _REFRESH_AND_READ_LUA,
            2,
            _session_key(session_id),
            _csrf_key(session_id),
            str(now),
            str(self._cfg.sliding_time_to_live_seconds),
            str(self._cfg.absolute_time_to_live_seconds),
        )

        if not result:
            self.log_event(SessionEvent.CSRF_FAILED, session_id=session_id, log_level=logging.WARNING)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")

        session_json, csrf_raw, _ttl = result
        stored_csrf = _decode_bytes(csrf_raw) if csrf_raw else ""
        if not secrets.compare_digest(stored_csrf or "", csrf_header):
            self.log_event(SessionEvent.CSRF_FAILED, session_id=session_id, log_level=logging.WARNING)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")

        session_data = _parse_session_payload(session_json, session_id, self.log_event)
        if not session_data:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        if not self._check_fingerprint(request, session_id, session_data):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        return {**session_data, "session_id": session_id}

    def _effective_ttl(self, created_at_timestamp_seconds: int) -> int:
        age = max(0, _now_seconds() - created_at_timestamp_seconds)
        remaining_absolute = self._cfg.absolute_time_to_live_seconds - age
        if remaining_absolute <= 0:
            return 0
        return min(self._cfg.sliding_time_to_live_seconds, remaining_absolute)

    def _check_fingerprint(
        self,
        request: Request,
        session_id: str,
        session_data: SessionData,
    ) -> bool:
        if not self._cfg.enable_session_binding:
            return True

        stored = session_data.get("request_fingerprint")
        if not stored:
            self.log_event(
                SessionEvent.SESSION_BINDING_MISMATCH,
                session_id=session_id,
                user_id=session_data["user_id"],
                log_level=logging.WARNING,
            )
            return False

        if stored != _fingerprint(request):
            self.log_event(
                SessionEvent.SESSION_BINDING_MISMATCH,
                session_id=session_id,
                user_id=session_data["user_id"],
                log_level=logging.WARNING,
            )
            task = asyncio.create_task(
                self.delete_session(
                    session_id=session_id, user_id=session_data["user_id"]
                )
            )
            task.add_done_callback(lambda _: None)
            return False

        return True


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
    cfg = SessionConfiguration(
        sliding_time_to_live_seconds=sliding_time_to_live_seconds,
        absolute_time_to_live_seconds=absolute_time_to_live_seconds,
        enable_session_binding=enable_session_binding,
        maximum_sessions_per_user=maximum_sessions_per_user,
        cookie_secure=cookie_secure,
    )
    return SessionManager(
        redis_client=redis_client,
        session_configuration=cfg,
        signing_secret=signing_secret,
    )
