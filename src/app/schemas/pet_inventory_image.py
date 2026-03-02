from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..core.enums import MimeType
from ..core.schemas import PersistentDeletion, TimestampSchema
from ..core.validators import ALLOWED_IMAGE_EXTENSIONS, validate_object_key_extension


class PetInventoryImageBase(BaseModel):
    object_key: Annotated[str, Field(min_length=1, max_length=1024, examples=["path/to/image.jpg"])]
    sort_order: Annotated[int, Field(ge=0, examples=[0, 1, 2])]

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, v):
        if any(ch.isspace() for ch in v):
            raise ValueError("object_key must not contain whitespace")

        if "\\" in v or "'" in v or '"' in v:
            raise ValueError("object_key must not contain backslashes or quotes")

        if any(ch for ch in v if not ch.isprintable()):
            raise ValueError("object_key must not contain control characters")

        if v.startswith("/"):
            raise ValueError("object_key must be a relative path")

        if "//" in v:
            raise ValueError("object_key must not contain empty path segments")

        parts = v.split("/")
        if "." in parts or ".." in parts:
            raise ValueError("object_key must not contain '.' or '..' path segments")

        if v.endswith("/"):
            raise ValueError("object_key must not end with '/'")

        v = validate_object_key_extension(v, ALLOWED_IMAGE_EXTENSIONS)

        return v


class PetInventoryImage(TimestampSchema, PetInventoryImageBase, PersistentDeletion):
    inventory_id: int
    mime_type: MimeType | None = None


class PetInventoryImageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    inventory_id: int
    image_url: str
    sort_order: int
    created_at: datetime
    mime_type: MimeType | None


class PetInventoryImageCreate(PetInventoryImageBase):
    model_config = ConfigDict(extra="forbid")


class PetInventoryImageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[int | None, Field(gt=0, default=None)]
    object_key: Annotated[
        str | None,
        Field(
            min_length=1,
            max_length=1024,
            examples=["path/to/image.jpg"],
            default=None,
        ),
    ]
    sort_order: Annotated[int, Field(ge=0, examples=[0, 1, 2])]

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, v: str | None) -> str | None:
        if v is None:
            return None

        if any(ch.isspace() for ch in v):
            raise ValueError("object_key must not contain whitespace")

        if "\\" in v or "'" in v or '"' in v:
            raise ValueError("object_key must not contain backslashes or quotes")

        if any(ch for ch in v if not ch.isprintable()):
            raise ValueError("object_key must not contain control characters")

        if v.startswith("/"):
            raise ValueError("object_key must be a relative path")

        if "//" in v:
            raise ValueError("object_key must not contain empty path segments")

        parts = v.split("/")
        if "." in parts or ".." in parts:
            raise ValueError("object_key must not contain '.' or '..' path segments")

        if v.endswith("/"):
            raise ValueError("object_key must not end with '/'")

        v = validate_object_key_extension(v, ALLOWED_IMAGE_EXTENSIONS)

        return v

    @model_validator(mode="after")
    def validate_existing_or_new_image(self):
        has_id = self.id is not None
        has_object_key = self.object_key is not None

        if has_id and has_object_key:
            raise ValueError("Provide either id (existing) or object_key (new), not both")

        if not has_id and not has_object_key:
            raise ValueError("Provide id (existing) or object_key (new)")

        return self
