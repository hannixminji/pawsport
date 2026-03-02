import logging
from dataclasses import dataclass
from typing import Any, ClassVar

from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from ..core.enums import AttachmentMimeType, FileExtension
from ..core.exceptions.domain_exceptions import InvalidInputError
from ..core.schemas import Actor
from ..core.utils.google_cloud_storage import generate_upload_signed_post_policy
from ..schemas.upload import SignedPostPolicyResponse

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class UploadService:
    db: AsyncSession

    SUPPORTED_FILE_TYPES: ClassVar[dict[FileExtension, AttachmentMimeType]] = {
        FileExtension.JPG: AttachmentMimeType.JPEG,
        FileExtension.JPEG: AttachmentMimeType.JPEG,
        FileExtension.PNG: AttachmentMimeType.PNG,
        FileExtension.PDF: AttachmentMimeType.PDF,
    }

    MAX_BYTES_BY_EXTENSION: ClassVar[dict[FileExtension, int]] = {
        FileExtension.JPG: 5 * 1024 * 1024,
        FileExtension.JPEG: 5 * 1024 * 1024,
        FileExtension.PNG: 5 * 1024 * 1024,
        FileExtension.PDF: 20 * 1024 * 1024,
    }

    IMAGE_ONLY_TYPES: ClassVar[frozenset[FileExtension]] = frozenset({
        FileExtension.JPG,
        FileExtension.JPEG,
        FileExtension.PNG,
    })

    DOCUMENT_ONLY_TYPES: ClassVar[frozenset[FileExtension]] = frozenset({
        FileExtension.PDF,
    })

    MAX_FILES_PER_REQUEST: ClassVar[int] = 10

    def _validate_and_get_file_info(
        self,
        filename: str,
        allowed_extensions: frozenset[FileExtension] | None = None,
    ) -> tuple[FileExtension, AttachmentMimeType]:
        if "." not in filename:
            raise InvalidInputError(f"Filename '{filename}' must have a valid extension")

        raw_ext = filename.rsplit(".", 1)[-1].lower()

        try:
            extension = FileExtension(raw_ext)
        except ValueError:
            allowed = allowed_extensions or frozenset(self.SUPPORTED_FILE_TYPES.keys())
            supported = ", ".join(sorted(allowed)).upper()
            raise InvalidInputError(f"Filename '{filename}' must be one of: {supported}")

        allowed = allowed_extensions or frozenset(self.SUPPORTED_FILE_TYPES.keys())

        if extension not in allowed:
            supported = ", ".join(sorted(allowed)).upper()
            raise InvalidInputError(f"Filename '{filename}' must be one of: {supported}")

        return extension, self.SUPPORTED_FILE_TYPES[extension]

    async def _generate_signed_post_policies(
        self,
        *,
        actor: Actor,
        filenames: list[str],
        allowed_extensions: frozenset[FileExtension] | None = None,
    ) -> SignedPostPolicyResponse:
        if not filenames:
            raise InvalidInputError("At least one filename must be provided.")

        if len(filenames) > self.MAX_FILES_PER_REQUEST:
            raise InvalidInputError(f"Cannot upload more than {self.MAX_FILES_PER_REQUEST} files at once.")

        uploads: list[dict[str, Any]] = []

        for filename in filenames:
            extension, content_type = self._validate_and_get_file_info(
                filename, allowed_extensions=allowed_extensions
            )
            max_bytes = self.MAX_BYTES_BY_EXTENSION[extension]
            object_key = f"{uuid7()}.{extension}"

            metadata = {
                "original_filename": filename,
                "mime_type": content_type,
                "uploader_user_id": str(actor.id),
            }

            LOGGER.info(
                "Generating signed upload policy",
                extra={
                    "actor_id": str(actor.id),
                    "filename": filename,
                    "extension": extension,
                    "content_type": content_type,
                },
            )

            post_policy = generate_upload_signed_post_policy(
                blob_name=object_key,
                content_type=content_type,
                max_size_bytes=max_bytes,
                metadata=metadata,
            )

            uploads.append(
                {
                    "original_filename": filename,
                    "object_key": object_key,
                    "upload": post_policy,
                    "content_type": content_type,
                    "max_size_bytes": max_bytes,
                }
            )

        return {"uploads": uploads}

    async def generate_image_upload_policies(
        self,
        *,
        actor: Actor,
        filenames: list[str],
    ) -> SignedPostPolicyResponse:
        return await self._generate_signed_post_policies(
            actor=actor,
            filenames=filenames,
            allowed_extensions=self.IMAGE_ONLY_TYPES,
        )

    async def generate_document_upload_policies(
        self,
        *,
        actor: Actor,
        filenames: list[str],
    ) -> SignedPostPolicyResponse:
        return await self._generate_signed_post_policies(
            actor=actor,
            filenames=filenames,
            allowed_extensions=self.DOCUMENT_ONLY_TYPES,
        )
