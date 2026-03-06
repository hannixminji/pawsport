from datetime import datetime

from pydantic import BaseModel, ConfigDict

from ..core.enums import ActionStatus


class SystemActionLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int

    actor_type: str
    action: str
    status: ActionStatus

    is_superuser: bool
    is_anonymous: bool

    actor_id: int | None
    actor_email: str | None
    role_ids: list[int] | None
    resource_type: str | None
    resource_id: str | None
    error_code: str | None
    error_message: str | None
    request_id: str | None
    ip_address: str | None
    user_agent: str | None
    before_state: dict | None
    after_state: dict | None
    extra_metadata: dict | None
    duration_ms: int | None

    created_at: datetime
