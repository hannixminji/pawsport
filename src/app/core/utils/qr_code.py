import io
from typing import Literal

import segno
from google.cloud import storage

from ...core.config import settings

storage_client = storage.Client()


def generate_qr_stream(
    data: str,
    scale: int = 10,
    error: Literal["L","M","Q","H"] = "H",
    kind: Literal["png","svg"] = "png"
) -> io.BytesIO:
    buffer = io.BytesIO()
    qr = segno.make(data, error=error)
    qr.save(buffer, kind=kind, scale=scale)
    buffer.seek(0)
    return buffer


def upload_qr_to_gcs_stream(
    buffer: io.BytesIO,
    object_key: str,
    kind: Literal["png","svg"] = "png"
) -> str:
    bucket = storage_client.bucket(settings.GCS_BUCKET_NAME)
    blob = bucket.blob(object_key)
    content_type = "image/png" if kind == "png" else "image/svg+xml"
    blob.upload_from_file(buffer, content_type=content_type)
    return object_key


def generate_qr_and_upload_gcs(
    data: str,
    object_key: str,
    scale: int = 10,
    error: Literal["L","M","Q","H"] = "H",
    kind: Literal["png","svg"] = "png"
) -> str:
    buffer = generate_qr_stream(data, scale=scale, error=error, kind=kind)
    return upload_qr_to_gcs_stream(buffer, object_key, kind=kind)
