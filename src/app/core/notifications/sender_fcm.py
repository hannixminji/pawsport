from __future__ import annotations

from typing import Final

from firebase_admin import exceptions as fb_exceptions
from firebase_admin import messaging

FCM_MAX_TOKENS_PER_MULTICAST_REQUEST: Final[int] = 500

_INVALID_TOKEN_MARKERS: Final[tuple[str, ...]] = (
    "registration-token-not-registered",
    "not registered",
    "invalid-registration-token",
    "invalid registration token",
    "not a valid fcm registration token",
)


def _is_dead_token_exception(exc: Exception | None) -> bool:
    if exc is None:
        return False

    if isinstance(exc, messaging.UnregisteredError):
        return True

    if isinstance(exc, fb_exceptions.InvalidArgumentError):
        msg = str(exc).lower()
        return any(m in msg for m in _INVALID_TOKEN_MARKERS)

    return False


async def send_fcm_multicast_notifications_in_chunks(
    *,
    registration_tokens: list[str],
    notification_title: str,
    notification_body: str,
    notification_data: dict[str, str],
) -> list[str]:
    registration_tokens = list(dict.fromkeys(registration_tokens))
    if not registration_tokens:
        return []

    invalid_tokens: list[str] = []

    for start in range(0, len(registration_tokens), FCM_MAX_TOKENS_PER_MULTICAST_REQUEST):
        token_chunk = registration_tokens[start : start + FCM_MAX_TOKENS_PER_MULTICAST_REQUEST]

        message = messaging.MulticastMessage(
            notification=messaging.Notification(
                title=notification_title,
                body=notification_body,
            ),
            data=notification_data,
            tokens=token_chunk,
        )

        batch_response: messaging.BatchResponse = await messaging.send_each_for_multicast_async(message)

        for idx, resp in enumerate(batch_response.responses):
            if (not resp.success) and _is_dead_token_exception(resp.exception):
                invalid_tokens.append(token_chunk[idx])

    return list(dict.fromkeys(invalid_tokens))
