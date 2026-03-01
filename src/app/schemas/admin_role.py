from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.schemas import TimestampSchema
from .admin_permission import AdminPermissionRead


class AdminRoleBase(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=100, examples=["Manager"])]
    description: Annotated[str | None, Field(max_length=1_000, examples=["Manage user accounts"], default=None)]

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v


class AdminRole(TimestampSchema, AdminRoleBase):
    pass


class AdminRoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    updated_at: datetime
    description: str | None


class AdminRoleReadWithPermissions(AdminRoleRead):
    permissions: list[AdminPermissionRead]


class AdminRoleCreate(AdminRoleBase):
    model_config = ConfigDict(extra="forbid")


class AdminRoleAssignPermissions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permission_ids: list[int] = Field(..., min_length=1, max_length=100)

    @field_validator("permission_ids")
    def validate_positive_ids(cls: type, v: list[int]) -> list[int]:
        for permission_id in v:
            if permission_id < 1:
                raise ValueError(f"Invalid permission ID: {permission_id}. Permission IDs must be positive integers.")

        return v


class AdminRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str | None, Field(min_length=1, max_length=100, examples=["Manager"], default=None)]
    description: Annotated[str | None, Field(max_length=1_000, examples=["Manage user accounts"], default=None)]

    @field_validator("name", "description", mode="before")
    @classmethod
    def normalize_text_fields(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v
