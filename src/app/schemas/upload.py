from typing import Annotated, Any

from pydantic import BaseModel, Field


class SignedPostPolicyRequest(BaseModel):
    filenames: Annotated[list[str], Field(min_length=1, max_length=255)]


class SignedPostPolicyUpload(BaseModel):
    original_filename: str
    object_key: str
    upload: dict[str, Any]
    content_type: str
    max_size_bytes: int


class SignedPostPolicyResponse(BaseModel):
    uploads: Annotated[list[SignedPostPolicyUpload], ...]
