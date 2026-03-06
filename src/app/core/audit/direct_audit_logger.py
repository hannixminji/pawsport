import time
from dataclasses import dataclass

from ...services.system_action_log import SystemActionLogService
from ..enums import ActionStatus
from ..schemas import Actor


@dataclass(slots=True)
class DirectAuditLogger:
    log_service: SystemActionLogService

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
        await self.log_service.log(
            actor=actor,
            action=action,
            status=status,
            resource_type=resource_type,
            resource_id=resource_id,
            error_code=error_code,
            error_message=error_message,
            before_state=before_state,
            after_state=after_state,
            extra_metadata=extra_metadata,
            duration_ms=round((time.monotonic() - actor.start_time) * 1000),
        )
