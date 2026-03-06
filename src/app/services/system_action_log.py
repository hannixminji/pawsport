import logging
from dataclasses import dataclass
from typing import Any, ClassVar

from sqlalchemy import func, insert, select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.enums import ActionStatus, ActorType
from ..core.exceptions.authorization_exceptions import ForbiddenError
from ..core.exceptions.domain_exceptions import NotFoundError
from ..core.schemas import Actor, PaginatedResponse
from ..core.search_engine.engine import SearchEngine
from ..core.search_engine.enums import FilterOp
from ..core.search_engine.schemas import SearchRequest
from ..core.utils.pagination import compute_offset
from ..models.system_action_log import SystemActionLog
from ..schemas.system_action_log import SystemActionLogRead

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SystemActionLogService:
    db: AsyncSession

    ADMIN_SEARCH_BLACKLIST_COLUMNS: ClassVar[frozenset[str]] = frozenset({
        "id",
        "before_state",
        "after_state",
        "extra_metadata",
        "user_agent",
    })
    ALLOWED_FILTER_OPERATORS_BY_COLUMN: ClassVar[dict] = {
        "actor_id": frozenset({
            FilterOp.EQ,
        }),
        "actor_type": frozenset({
            FilterOp.EQ,
            FilterOp.IN,
        }),
        "actor_email": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
        }),
        "action": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
            FilterOp.IN,
        }),
        "resource_type": frozenset({
            FilterOp.EQ,
            FilterOp.IN,
        }),
        "resource_id": frozenset({
            FilterOp.EQ,
        }),
        "status": frozenset({
            FilterOp.EQ,
            FilterOp.IN,
        }),
        "error_code": frozenset({
            FilterOp.EQ,
            FilterOp.IN,
        }),
        "request_id": frozenset({
            FilterOp.EQ,
        }),
        "ip_address": frozenset({
            FilterOp.EQ,
        }),
        "created_at": frozenset({
            FilterOp.LT,
            FilterOp.LTE,
            FilterOp.GT,
            FilterOp.GTE,
        }),
    }
    SEARCH_SORTABLE_COLUMNS: ClassVar[set[str]] = {
        "action",
        "actor_email",
        "status",
        "duration_ms",
        "created_at",
    }

    @staticmethod
    def _build_insert_values(
        *,
        actor: Actor | None,
        action: str,
        status: ActionStatus,
        resource_type: str | None,
        resource_id: str | None,
        error_code: str | None,
        error_message: str | None,
        before_state: dict[str, Any] | None,
        after_state: dict[str, Any] | None,
        extra_metadata: dict[str, Any] | None,
        duration_ms: int | None,
    ) -> dict[str, Any]:
        return {
            "actor_type": actor.actor_type.value if actor else ActorType.SYSTEM.value,
            "action": action,
            "status": status,
            "is_superuser": actor.is_superuser if actor else False,
            "is_anonymous": actor.is_anonymous if actor else False,
            "actor_id": actor.id if actor else None,
            "actor_email": getattr(actor, "email", None),
            "role_ids": actor.role_ids if actor else None,
            "resource_type": resource_type,
            "resource_id": str(resource_id) if resource_id is not None else None,
            "error_code": error_code,
            "error_message": (error_message or "")[:2048] or None,
            "request_id": actor.request_id if actor else None,
            "ip_address": actor.ip_address if actor else None,
            "user_agent": actor.user_agent if actor else None,
            "before_state": before_state,
            "after_state": after_state,
            "extra_metadata": extra_metadata,
            "duration_ms": duration_ms,
        }

    async def log(
        self,
        *,
        actor: Actor | None,
        action: str,
        status: ActionStatus = ActionStatus.SUCCESS,
        resource_type: str | None = None,
        resource_id: int | str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        values = self._build_insert_values(
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
            duration_ms=duration_ms,
        )

        statement = (
            insert(SystemActionLog)
            .values(**values)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError:
            await self.db.rollback()

            LOGGER.error(
                "Transient DB error while writing action log; entry dropped.",
                extra={"action": action, "actor_id": values["actor_id"]},
                exc_info=True,
            )

        except SQLAlchemyError:
            await self.db.rollback()

            LOGGER.error(
                "Non-transient DB error while writing action log; entry dropped.",
                extra={"action": action, "actor_id": values["actor_id"]},
                exc_info=True,
            )

        except Exception:
            await self.db.rollback()

            LOGGER.exception(
                "Unexpected error while writing action log; entry dropped.",
                extra={"action": action, "actor_id": values["actor_id"]},
            )

    async def search(
        self,
        *,
        actor: Actor,
        search_request: SearchRequest,
    ) -> PaginatedResponse[SystemActionLogRead]:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to search action logs.")

        engine = SearchEngine(
            db=self.db,
            model=SystemActionLog,
            blacklisted_columns=self.ADMIN_SEARCH_BLACKLIST_COLUMNS,
            allowed_ops=self.ALLOWED_FILTER_OPERATORS_BY_COLUMN,
            column_order_map=None,
            sortable_columns=self.SEARCH_SORTABLE_COLUMNS,
            max_in_list_size=100,
            max_depth=10,
        )

        base_query = (
            select(SystemActionLog)
            .order_by(SystemActionLog.created_at.desc())
        )
        result = await engine.search(
            base_query=base_query,
            values=search_request,
            serializer=SystemActionLogRead.model_validate,
        )

        return PaginatedResponse[SystemActionLogRead](
            data=result.data,
            total_count=result.total_count,
            has_more=(result.page * result.items_per_page) < result.total_count,
            page=result.page,
            items_per_page=result.items_per_page,
        )

    async def get_logs(
        self,
        *,
        actor: Actor,
        page: int,
        items_per_page: int,
    ) -> PaginatedResponse[SystemActionLogRead]:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to view action logs.")

        db_logs = (
            await self.db.execute(
                select(SystemActionLog)
                .order_by(SystemActionLog.created_at.desc())
                .offset(compute_offset(page, items_per_page))
                .limit(items_per_page)
            )
        ).scalars().all()

        total_count = (
            await self.db.execute(
                select(func.count())
                .select_from(SystemActionLog)
            )
        ).scalar_one()

        return PaginatedResponse[SystemActionLogRead](
            data=[SystemActionLogRead.model_validate(log) for log in db_logs],
            total_count=total_count,
            has_more=(page * items_per_page) < total_count,
            page=page,
            items_per_page=items_per_page,
        )

    async def get_log(
        self,
        *,
        actor: Actor,
        log_id: int,
    ) -> SystemActionLogRead:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to view an action log entry.")

        db_log = (
            await self.db.execute(
                select(SystemActionLog)
                .where(SystemActionLog.id == log_id)
            )
        ).scalar_one_or_none()
        if db_log is None:
            raise NotFoundError("Action log entry not found.")

        return SystemActionLogRead.model_validate(db_log)
