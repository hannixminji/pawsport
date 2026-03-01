import asyncio
import logging
from typing import Final

from firebase_admin import exceptions as fb_exceptions
from firebase_admin import messaging

logger = logging.getLogger(__name__)

FCM_MAX_TOKENS_PER_MULTICAST_REQUEST: Final[int] = 500
_FCM_MAX_CONCURRENT_CHUNKS: Final[int] = 5

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


def _build_multicast_message(
    tokens: list[str],
    title: str,
    body: str,
    data: dict[str, str],
) -> messaging.MulticastMessage:
    return messaging.MulticastMessage(
        notification=messaging.Notification(title=title, body=body),
        data=data,
        tokens=tokens,
    )


async def _send_chunk(
    tokens: list[str],
    title: str,
    body: str,
    data: dict[str, str],
) -> list[str]:
    message = _build_multicast_message(tokens, title, body, data)

    try:
        batch_response: messaging.BatchResponse = await messaging.send_each_for_multicast_async(message)
    except fb_exceptions.FirebaseError as e:
        logger.error("FCM chunk failed completely (FirebaseError): %s", e)
        return []
    except Exception as e:
        logger.exception("Unexpected error while sending FCM chunk: %s", e)
        return []

    invalid: list[str] = []
    for idx, resp in enumerate(batch_response.responses):
        if resp.success:
            continue
        if _is_dead_token_exception(resp.exception):
            invalid.append(tokens[idx])
        else:
            logger.warning(
                "FCM delivery failed for token (non-fatal): %s",
                resp.exception,
                extra={"token_prefix": tokens[idx][:10]},
            )

    return invalid


async def send_fcm_multicast_notifications_in_chunks(
    *,
    registration_tokens: list[str],
    notification_title: str,
    notification_body: str,
    notification_data: dict[str, str],
) -> list[str]:
    unique_tokens = list(dict.fromkeys(registration_tokens))
    if not unique_tokens:
        return []

    chunks = [
        unique_tokens[i : i + FCM_MAX_TOKENS_PER_MULTICAST_REQUEST]
        for i in range(0, len(unique_tokens), FCM_MAX_TOKENS_PER_MULTICAST_REQUEST)
    ]

    logger.info(
        "Sending FCM notifications: %d tokens across %d chunks",
        len(unique_tokens),
        len(chunks),
    )

    semaphore = asyncio.Semaphore(_FCM_MAX_CONCURRENT_CHUNKS)

    async def _guarded_send_chunk(tokens: list[str]) -> list[str]:
        async with semaphore:
            return await _send_chunk(tokens, notification_title, notification_body, notification_data)

    results: list[list[str]] = await asyncio.gather(
        *[_guarded_send_chunk(chunk) for chunk in chunks],
        return_exceptions=False,
    )

    invalid_tokens = [token for chunk_result in results for token in chunk_result]

    if invalid_tokens:
        logger.info("FCM found %d dead tokens to purge", len(invalid_tokens))

    return list(dict.fromkeys(invalid_tokens))
