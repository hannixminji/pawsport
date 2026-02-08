import io
from collections.abc import Mapping
from datetime import timedelta
from functools import lru_cache
from typing import Any, cast

from google.api_core.exceptions import NotFound
from google.cloud import storage
from PIL import Image

from ...core.config import settings
from ...core.type_aliases import HttpMethod, ImageMimeType, SignedUrlVersion


@lru_cache(maxsize=1)
def get_storage_client() -> storage.Client:
    if settings.GOOGLE_APPLICATION_CREDENTIALS_JSON:
        import base64
        import json
        from google.oauth2 import service_account

        secret_value = settings.GOOGLE_APPLICATION_CREDENTIALS_JSON.get_secret_value().strip().strip("'").strip('"')
        
        try:
            # Try decoding as base64 first
            decoded_bytes = base64.b64decode(secret_value)
            decoded_str = decoded_bytes.decode("utf-8")
            info = json.loads(decoded_str)
        except (ValueError, base64.binascii.Error):
            # Fallback to plain JSON string if not base64
            try:
                info = json.loads(secret_value)
            except json.JSONDecodeError as e:
                # Log a masked snippet of the value to help debugging without leaking the full key
                masked = secret_value[:10] + "..." if len(secret_value) > 10 else secret_value
                raise ValueError(f"Failed to decode credentials. Value starts with: {masked}. Error: {e}")

        credentials = service_account.Credentials.from_service_account_info(info)
        return storage.Client(credentials=credentials)
    return storage.Client()


def generate_signed_url(
    blob_name: str,
    expiration_minutes: int,
    bucket_name: str | None = None,
    method: HttpMethod = "GET",
    content_type: str | None = None,
    response_disposition: str | None = None,
    headers: dict[str, str] | None = None,
    query_parameters: dict[str, str] | None = None,
    version: SignedUrlVersion | None = None,
) -> str:
    bucket_name = bucket_name or settings.GCS_BUCKET_NAME
    version = version or cast(SignedUrlVersion, settings.GCS_SIGNED_URL_VERSION)

    storage_client = get_storage_client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)

    return cast(
        str,
        blob.generate_signed_url(
            expiration=timedelta(minutes=expiration_minutes),
            method=method,
            content_type=content_type,
            response_disposition=response_disposition,
            headers=headers,
            query_parameters=query_parameters,
            version=version,
        ),
    )


def generate_view_signed_url(blob_name: str) -> str:
    return generate_signed_url(
        blob_name=blob_name,
        expiration_minutes=settings.GCS_VIEW_SIGNED_URL_EXPIRATION_MINUTES,
    )


def generate_download_signed_url(blob_name: str) -> str:
    return generate_signed_url(
        blob_name=blob_name,
        expiration_minutes=settings.GCS_DOWNLOAD_SIGNED_URL_EXPIRATION_MINUTES,
        response_disposition=f'attachment; filename="{blob_name}"',
    )


def generate_upload_signed_url(
    blob_name: str,
    content_type: ImageMimeType | str,
    metadata: Mapping[str, str] | None = None,
) -> str:
    headers: dict[str, str] = {}

    if metadata:
        for key, value in metadata.items():
            headers[f"x-goog-meta-{key.lower()}"] = value

    return generate_signed_url(
        blob_name=blob_name,
        expiration_minutes=settings.GCS_UPLOAD_SIGNED_URL_EXPIRATION_MINUTES,
        method="PUT",
        content_type=str(content_type),
        headers=headers,
    )


def generate_upload_signed_post_policy(
    blob_name: str,
    content_type: ImageMimeType | str,
    max_size_bytes: int,
    metadata: Mapping[str, str] | None = None,
    bucket_name: str | None = None,
) -> dict[str, Any]:
    bucket_name = bucket_name or settings.GCS_BUCKET_NAME

    required_fields: dict[str, str] = {
        "Content-Type": str(content_type),
    }

    conditions: list[Any] = [
        ["content-length-range", 0, max_size_bytes],
        ["eq", "$Content-Type", str(content_type)],
    ]

    if metadata:
        for key, value in metadata.items():
            meta_key = f"x-goog-meta-{key.lower()}"
            required_fields[meta_key] = value
            conditions.append(["eq", f"${meta_key}", value])

    storage_client = get_storage_client()
    policy = storage_client.generate_signed_post_policy_v4(
        bucket_name=bucket_name,
        blob_name=blob_name,
        expiration=timedelta(minutes=settings.GCS_UPLOAD_SIGNED_URL_EXPIRATION_MINUTES),
        fields=required_fields,
        conditions=conditions,
        scheme="https",
    )

    return policy


def generate_resumable_upload_signed_url(blob_name: str, content_type: ImageMimeType) -> str:
    return generate_signed_url(
        blob_name=blob_name,
        expiration_minutes=settings.GCS_RESUMABLE_UPLOAD_SIGNED_URL_EXPIRATION_MINUTES,
        method="POST",
        content_type=str(content_type),
        headers={"x-goog-resumable": "start"},
    )


def load_images(blob_names: list[str], bucket_name: str | None = None) -> dict[str, Image.Image]:
    bucket_name = bucket_name or settings.GCS_BUCKET_NAME

    storage_client = get_storage_client()
    bucket = storage_client.bucket(bucket_name)

    images: dict[str, Image.Image] = {}

    for blob_name in blob_names:
        blob = bucket.blob(blob_name)
        if blob.exists():
            image_bytes = blob.download_as_bytes()
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            images[blob_name] = image

    return images


def is_objects_exist(blob_names: list[str], bucket_name: str | None = None) -> dict[str, bool]:
    bucket_name = bucket_name or settings.GCS_BUCKET_NAME

    storage_client = get_storage_client()
    bucket = storage_client.bucket(bucket_name)

    results: dict[str, bool] = {}

    for blob_name in blob_names:
        blob = bucket.blob(blob_name)
        results[blob_name] = blob.exists()

    return results


def get_object_metadata(blob_name: str, bucket_name: str | None = None) -> dict[str, str] | None:
    bucket_name = bucket_name or settings.GCS_BUCKET_NAME

    storage_client = get_storage_client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.get_blob(blob_name)

    if blob is None:
        return None

    return blob.metadata or {}


def get_objects_metadata(
    blob_names: list[str],
    bucket_name: str | None = None,
) -> dict[str, dict[str, str]]:
    bucket_name = bucket_name or settings.GCS_BUCKET_NAME

    storage_client = get_storage_client()
    bucket = storage_client.bucket(bucket_name)

    results: dict[str, dict[str, str]] = {}
    for blob_name in blob_names:
        blob = bucket.blob(blob_name)
        try:
            blob.reload(client=storage_client)
            results[blob_name] = blob.metadata or {}
        except NotFound:
            results[blob_name] = {}

    return results
