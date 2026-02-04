from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, NotRequired, TypedDict

from fastapi import HTTPException, Request, status
from itsdangerous import BadSignature, URLSafeSerializer
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


@dataclass(frozen=True)
class SessionConfiguration:
    sliding_time_to_live_seconds: int
    absolute_time_to_live_seconds: int
    enable_session_binding: bool = True
    maximum_sessions_per_user: int = 10


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


def validate_signing_secret(signing_secret: str) -> None:
    if not signing_secret or len(signing_secret) < 32:
        raise RuntimeError("ADMIN_SESSION_SIGNING_SECRET must be set and at least 32 characters long")


def session_redis_key(session_id: str) -> str:
    return f"{SESSION_REDIS_KEY_PREFIX}{session_id}"


def csrf_redis_key(session_id: str) -> str:
    return f"{CSRF_REDIS_KEY_PREFIX}{session_id}"


def user_sessions_redis_key(user_id: int) -> str:
    return f"{USER_SESSIONS_REDIS_KEY_PREFIX}{user_id}"


def compute_request_fingerprint(request: Request) -> str:
    user_agent_header = request.headers.get("user-agent", "")
    accept_language_header = request.headers.get("accept-language", "")
    fingerprint_input_bytes = f"{user_agent_header}|{accept_language_header}".encode("utf-8", errors="ignore")
    return hashlib.sha256(fingerprint_input_bytes).hexdigest()[:16]


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
        validate_signing_secret(signing_secret)
        self._redis_client = redis_client
        self._session_configuration = session_configuration
        self._serializer = URLSafeSerializer(signing_secret, salt=SESSION_SIGNING_SALT)

    def sign_session_id(self, session_id: str) -> str:
        return self._serializer.dumps({"session_id": session_id})

    def unsign_session_id(self, signed_session_cookie_value: str) -> str | None:
        try:
            payload = self._serializer.loads(signed_session_cookie_value)
        except BadSignature:
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
            log_payload["session_id"] = session_id
        if user_id is not None:
            log_payload["user_id"] = user_id
        if details:
            log_payload.update(details)
        logger.log(log_level, event.value, extra=log_payload)

    async def enforce_maximum_sessions_per_user(self, *, user_id: int) -> None:
        maximum_sessions = self._session_configuration.maximum_sessions_per_user
        user_sessions_key = user_sessions_redis_key(user_id)

        existing_sessions = await self._redis_client.zrange(user_sessions_key, 0, -1)
        if len(existing_sessions) < maximum_sessions:
            return

        number_to_evict = len(existing_sessions) - maximum_sessions + 1
        sessions_to_evict = existing_sessions[:number_to_evict]

        for session_identifier in sessions_to_evict:
            if isinstance(session_identifier, bytes):
                session_identifier = session_identifier.decode()
            await self.delete_session(session_id=str(session_identifier), user_id=user_id)

        self.log_event(
            SessionEvent.MAXIMUM_SESSIONS_EVICTED,
            user_id=user_id,
            details={"evicted_sessions": number_to_evict},
            log_level=logging.INFO,
        )

    async def create_session(
        self,
        *,
        request: Request,
        user_id: int,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        session_id = secrets.token_urlsafe(SESSION_IDENTIFIER_TOKEN_BYTES)
        csrf_token = secrets.token_urlsafe(CSRF_TOKEN_BYTES)
        created_at_timestamp_seconds = current_utc_timestamp_seconds()

        reserved_keys = {
            "user_id",
            "created_at_timestamp_seconds",
            "request_fingerprint",
            "session_id",
        }
        if metadata and any(key in reserved_keys for key in metadata.keys()):
            raise ValueError(f"metadata contains reserved keys: {sorted(reserved_keys)}")

        session_payload: dict[str, Any] = {
            "user_id": user_id,
            "created_at_timestamp_seconds": created_at_timestamp_seconds,
        }

        if self._session_configuration.enable_session_binding:
            session_payload["request_fingerprint"] = compute_request_fingerprint(request)

        if metadata:
            session_payload.update(metadata)

        serialized_session_payload = json.dumps(session_payload, separators=(",", ":"), default=str)

        expiration_seconds = effective_time_to_live_seconds(
            created_at_timestamp_seconds,
            self._session_configuration,
        )
        if expiration_seconds <= 0:
            raise RuntimeError("Session configuration produced a non-positive expiration_seconds")

        await self.enforce_maximum_sessions_per_user(user_id=user_id)

        async with self._redis_client.pipeline(transaction=True) as redis_pipeline:
            redis_pipeline.set(session_redis_key(session_id), serialized_session_payload, ex=expiration_seconds)
            redis_pipeline.set(csrf_redis_key(session_id), csrf_token, ex=expiration_seconds)
            redis_pipeline.zadd(user_sessions_redis_key(user_id), {session_id: created_at_timestamp_seconds})
            redis_pipeline.expire(
                user_sessions_redis_key(user_id),
                self._session_configuration.absolute_time_to_live_seconds,
            )
            await redis_pipeline.execute()

        self.log_event(SessionEvent.SESSION_CREATED, session_id=session_id, user_id=user_id)
        return session_id, csrf_token

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

    async def delete_session(self, *, session_id: str, user_id: int | None = None) -> None:
        resolved_user_id = user_id
        if resolved_user_id is None:
            existing_session = await self.read_session(session_id=session_id)
            resolved_user_id = existing_session["user_id"] if existing_session else None

        async with self._redis_client.pipeline(transaction=True) as redis_pipeline:
            redis_pipeline.delete(session_redis_key(session_id))
            redis_pipeline.delete(csrf_redis_key(session_id))
            if resolved_user_id is not None:
                redis_pipeline.zrem(user_sessions_redis_key(resolved_user_id), session_id)
            await redis_pipeline.execute()

        self.log_event(SessionEvent.SESSION_DELETED, session_id=session_id, user_id=resolved_user_id)

    async def refresh_session(self, *, session_id: str) -> bool:
        existing_session = await self.read_session(session_id=session_id)
        if not existing_session:
            await self.delete_session(session_id=session_id)
            self.log_event(SessionEvent.SESSION_EXPIRED, session_id=session_id, log_level=logging.INFO)
            return False

        expiration_seconds = effective_time_to_live_seconds(
            existing_session["created_at_timestamp_seconds"],
            self._session_configuration,
        )
        if expiration_seconds <= 0:
            await self.delete_session(session_id=session_id, user_id=existing_session["user_id"])
            self.log_event(SessionEvent.SESSION_EXPIRED, session_id=session_id, user_id=existing_session["user_id"])
            return False

        async with self._redis_client.pipeline(transaction=True) as redis_pipeline:
            redis_pipeline.expire(session_redis_key(session_id), expiration_seconds)
            redis_pipeline.expire(csrf_redis_key(session_id), expiration_seconds)
            await redis_pipeline.execute()

        self.log_event(SessionEvent.SESSION_REFRESHED, session_id=session_id, user_id=existing_session["user_id"])
        return True

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

        refreshed = await self.refresh_session(session_id=session_id)
        if not refreshed:
            return None

        existing_session = await self.read_session(session_id=session_id)
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

    async def enforce_csrf(self, *, request: Request) -> None:
        if request.method in SAFE_HTTP_METHODS:
            return

        signed_cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
        if not signed_cookie_value:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        session_id = self.unsign_session_id(signed_cookie_value)
        if not session_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        refreshed = await self.refresh_session(session_id=session_id)
        if not refreshed:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        csrf_header_value = request.headers.get("x-csrf-token")
        valid = await self.validate_csrf(session_id=session_id, csrf_token_from_header=csrf_header_value)
        if not valid:
            self.log_event(SessionEvent.CSRF_FAILED, session_id=session_id, log_level=logging.WARNING)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")

    async def rotate_session(self, *, request: Request, old_session_id: str) -> tuple[str, str]:
        existing_session = await self.read_session(session_id=old_session_id)
        if not existing_session:
            raise ValueError("Session not found")

        user_id = existing_session["user_id"]

        preserved_metadata: dict[str, Any] = {}
        for key, value in existing_session.items():
            if key in {"user_id", "created_at_timestamp_seconds", "request_fingerprint"}:
                continue
            preserved_metadata[key] = value

        new_session_id, new_csrf_token = await self.create_session(
            request=request,
            user_id=user_id,
            metadata=preserved_metadata if preserved_metadata else None,
        )

        await self.delete_session(session_id=old_session_id, user_id=user_id)
        self.log_event(SessionEvent.SESSION_ROTATED, session_id=new_session_id, user_id=user_id)
        return new_session_id, new_csrf_token

    async def delete_all_user_sessions(self, *, user_id: int) -> int:
        user_sessions_key = user_sessions_redis_key(user_id)
        session_identifiers = await self._redis_client.zrange(user_sessions_key, 0, -1)

        deleted_count = 0
        for session_identifier in session_identifiers:
            if isinstance(session_identifier, bytes):
                session_identifier = session_identifier.decode()
            await self.delete_session(session_id=str(session_identifier), user_id=user_id)
            deleted_count += 1

        return deleted_count


def create_session_manager(
    *,
    redis_client: Redis,
    sliding_time_to_live_seconds: int,
    absolute_time_to_live_seconds: int,
    enable_session_binding: bool = True,
    maximum_sessions_per_user: int = 10,
) -> SessionManager:
    signing_secret = settings.ADMIN_SESSION_SIGNING_SECRET.get_secret_value()
    validate_signing_secret(signing_secret)

    session_configuration = SessionConfiguration(
        sliding_time_to_live_seconds=sliding_time_to_live_seconds,
        absolute_time_to_live_seconds=absolute_time_to_live_seconds,
        enable_session_binding=enable_session_binding,
        maximum_sessions_per_user=maximum_sessions_per_user,
    )
    return SessionManager(
        redis_client=redis_client,
        session_configuration=session_configuration,
        signing_secret=signing_secret,
    )
