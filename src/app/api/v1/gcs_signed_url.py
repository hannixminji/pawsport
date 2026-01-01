from typing import Annotated

from fastapi import APIRouter, Query
from uuid6 import uuid7

from ...core.exceptions.http_exceptions import BadRequestException
from ...core.utils.google_cloud_storage import generate_upload_signed_url

router = APIRouter(tags=["uploads"])


@router.post("/upload/signed-url")
async def create_upload_signed_urls(
    filenames: Annotated[list[str], Query(min_length=1)]
) -> dict[str, list[dict]]:
    uploads = []

    for filename in filenames:
        if not filename.lower().endswith((".jpg", ".jpeg", ".png")):
            raise BadRequestException(f"Filename '{filename}' must be a JPG, JPEG, or PNG file")

        extension = filename.rsplit(".", 1)[-1].lower()
        content_type = "image/jpeg" if extension in ["jpg", "jpeg"] else "image/png"

        new_filename = f"{uuid7()}.{extension}"

        upload_url = generate_upload_signed_url(
            blob_name=new_filename,
            content_type=content_type
        )

        uploads.append({
            "original_filename": filename,
            "object_key": new_filename,
            "upload_url": upload_url,
            "content_type": content_type,
        })

    return {"uploads": uploads}
