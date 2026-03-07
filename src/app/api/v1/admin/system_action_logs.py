from typing import Annotated

from fastapi import Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter, csrf_exempt
from app.api.dependencies import get_current_superuser_actor
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache
from app.schemas.system_action_log import SystemActionLogRead
from app.services.system_action_log_service import SystemActionLogService

router = CSRFProtectedRouter(prefix="/system-logs", tags=["System Logs"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> SystemActionLogService:
    return SystemActionLogService(db=db)


SystemActionLogServiceDependency = Annotated[SystemActionLogService, Depends(get_service)]
SuperuserActorDependency = Annotated[Actor, Depends(get_current_superuser_actor)]


@csrf_exempt
@router.post("/search", response_model=PaginatedResponse[SystemActionLogRead], status_code=status.HTTP_200_OK)
async def search_system_logs(
    search_request: SearchRequest,
    actor: SuperuserActorDependency,
    service: SystemActionLogServiceDependency,
) -> PaginatedResponse[SystemActionLogRead]:
    return await service.search(actor=actor, search_request=search_request)


@router.get("", response_model=PaginatedResponse[SystemActionLogRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:system-logs:list",
    resource_id_name=["page", "items_per_page"],
    namespace="admin:system-logs",
    expiration=60,
)
async def list_system_logs(
    request: Request,
    actor: SuperuserActorDependency,
    service: SystemActionLogServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
) -> PaginatedResponse[SystemActionLogRead]:
    return await service.get_logs(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
    )


@router.get("/{log_id}", response_model=SystemActionLogRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:system-logs:detail",
    resource_id_name="log_id",
    expiration=60,
)
async def get_system_log(
    request: Request,
    log_id: int,
    actor: SuperuserActorDependency,
    service: SystemActionLogServiceDependency,
) -> SystemActionLogRead:
    return await service.get_log(actor=actor, log_id=log_id)
