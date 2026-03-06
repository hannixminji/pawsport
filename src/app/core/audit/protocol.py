from typing import Protocol

from ..enums import ActionStatus
from ..schemas import Actor


class AuditLogger(Protocol):
    async def log(
        self,
        *,
        actor: Actor,
        action: str,
        status: ActionStatus,
        resource_type: str,
        resource_id: int | str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        before_state: dict | None = None,
        after_state: dict | None = None,
        extra_metadata: dict | None = None,
    ) -> None:
        ...
