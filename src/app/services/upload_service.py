import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from ..core.exceptions.domain_exceptions import InvalidInputError
from ..core.schemas import Actor, PaginatedResponse
from ..core.utils.google_cloud_storage import generate_upload_signed_post_policy

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class UploadService:
    db: AsyncSession

    SUPPORTED_FILE_TYPES = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "pdf": "application/pdf",
    }
    MAX_UPLOAD_BYTES = 20 * 1024 * 1024

    def _validate_and_get_file_info(self, filename: str) -> tuple[str, str]:
        if "." not in filename:
            raise InvalidInputError(f"Filename '{filename}' must have a valid extension")

        extension = filename.rsplit(".", 1)[-1].lower()

        if extension not in self.SUPPORTED_FILE_TYPES:
            supported = ", ".join(self.SUPPORTED_FILE_TYPES.keys()).upper()
            raise InvalidInputError(f"Filename '{filename}' must be one of: {supported}")

        return extension, self.SUPPORTED_FILE_TYPES[extension]

    async def generate_signed_post_policies(
        self,
        *,
        actor: Actor,
        filenames: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        if not filenames:
            raise InvalidInputError("At least one filename must be provided.")

        uploads: list[dict[str, Any]] = []

        for filename in filenames:
            extension, content_type = self._validate_and_get_file_info(filename)
            object_key = f"{uuid7()}.{extension}"

            metadata = {
                "original_filename": filename,
                "mime_type": content_type,
                "uploader_user_id": str(actor.id),
            }

            post_policy = generate_upload_signed_post_policy(
                blob_name=object_key,
                content_type=content_type,
                max_size_bytes=self.MAX_UPLOAD_BYTES,
                metadata=metadata,
            )

            uploads.append(
                {
                    "original_filename": filename,
                    "object_key": object_key,
                    "upload": post_policy,
                    "content_type": content_type,
                    "max_size_bytes": self.MAX_UPLOAD_BYTES,
                }
            )

        return {"uploads": uploads}
