from typing import Annotated

from fastapi import APIRouter, Query
from uuid6 import uuid7

from ...core.exceptions.http_exceptions import BadRequestException
from ...core.utils.google_cloud_storage import generate_upload_signed_url

router = APIRouter(tags=["uploads"])

SUPPORTED_FILE_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",

    "pdf": "application/pdf",

    "mp4": "video/mp4",
}


def validate_and_get_file_info(filename: str) -> tuple[str, str]:
    if "." not in filename:
        raise BadRequestException(
            f"Filename '{filename}' must have a valid extension"
        )

    extension = filename.rsplit(".", 1)[-1].lower()

    if extension not in SUPPORTED_FILE_TYPES:
        supported = ", ".join(SUPPORTED_FILE_TYPES.keys()).upper()
        raise BadRequestException(
            f"Filename '{filename}' must be one of: {supported}"
        )

    return extension, SUPPORTED_FILE_TYPES[extension]


@router.post("/upload/signed-url")
async def create_upload_signed_urls(
    filenames: Annotated[list[str], Query(min_length=1, max_length=10)]
) -> dict[str, list[dict[str, str]]]:
    uploads: list[dict[str, str]] = []

    for filename in filenames:
        extension, content_type = validate_and_get_file_info(filename)

        object_key = f"{uuid7()}.{extension}"

        metadata = {
            "original_filename": filename,
            "file_type": extension,
        }

        upload_url = generate_upload_signed_url(
            blob_name=object_key,
            content_type=content_type,
            metadata=metadata,
        )

        uploads.append(
            {
                "original_filename": filename,
                "object_key": object_key,
                "upload_url": upload_url,
                "content_type": content_type,
            }
        )

    return {"uploads": uploads}
