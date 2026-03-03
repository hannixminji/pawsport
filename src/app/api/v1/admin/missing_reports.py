from typing import Annotated

from fastapi import Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter
from app.api.dependencies import get_current_admin_actor, get_current_superuser_actor
from app.core.db.database import async_get_db
from app.core.enums import MissingReportStatus
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.missing_report import MissingReportCreate, MissingReportRead, MissingReportUpdate
from app.services.missing_report_service import MissingReportService

router = CSRFProtectedRouter(prefix="/missing-reports", tags=["Missing Reports"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> MissingReportService:
    return MissingReportService(db=db)


MissingReportServiceDependency = Annotated[MissingReportService, Depends(get_service)]
AdminActorDependency = Annotated[Actor, Depends(get_current_admin_actor)]
SuperuserActorDependency = Annotated[Actor, Depends(get_current_superuser_actor)]


@router.post("/search", response_model=PaginatedResponse[MissingReportRead], status_code=status.HTTP_200_OK)
async def search_missing_reports(
    search_request: SearchRequest,
    actor: AdminActorDependency,
    service: MissingReportServiceDependency,
    user_id: Annotated[int | None, Query(alias="userId")] = None,
    pet_id: Annotated[int | None, Query(alias="petId")] = None,
) -> PaginatedResponse[MissingReportRead]:
    return await service.search(actor=actor, search_request=search_request, user_id=user_id, pet_id=pet_id)


@router.post("/{pet_id}", response_model=MissingReportRead, status_code=status.HTTP_201_CREATED)
async def create_missing_report(
    request: Request,
    pet_id: int,
    payload: MissingReportCreate,
    actor: AdminActorDependency,
    service: MissingReportServiceDependency,
) -> MissingReportRead:
    result = await service.create(actor=actor, pet_id=pet_id, report_input=payload)
    await invalidate_namespace("admin:missing-reports")
    return result


@router.get("", response_model=PaginatedResponse[MissingReportRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:missing-reports:list",
    resource_id_name=["page", "items_per_page", "user_id", "pet_id"],
    namespace="admin:missing-reports",
    expiration=60,
)
async def list_missing_reports(
    request: Request,
    actor: AdminActorDependency,
    service: MissingReportServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
    user_id: Annotated[int | None, Query(alias="userId")] = None,
    pet_id: Annotated[int | None, Query(alias="petId")] = None,
) -> PaginatedResponse[MissingReportRead]:
    return await service.get_missing_reports(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
        user_id=user_id,
        pet_id=pet_id,
    )


@router.get("/{missing_report_id}", response_model=MissingReportRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:missing-reports:detail",
    resource_id_name="missing_report_id",
    expiration=60,
)
async def get_missing_report(
    request: Request,
    missing_report_id: int,
    actor: AdminActorDependency,
    service: MissingReportServiceDependency,
) -> MissingReportRead:
    return await service.get_missing_report(actor=actor, missing_report_id=missing_report_id)


@router.patch("/{missing_report_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:missing-reports:detail",
    resource_id_name="missing_report_id",
    namespaces_to_invalidate=["admin:missing-reports"],
)
async def soft_delete_missing_report(
    request: Request,
    missing_report_id: int,
    actor: AdminActorDependency,
    service: MissingReportServiceDependency,
) -> None:
    await service.soft_delete(actor=actor, missing_report_id=missing_report_id)


@router.patch("/{missing_report_id}/status", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:missing-reports:detail",
    resource_id_name="missing_report_id",
    namespaces_to_invalidate=["admin:missing-reports"],
)
async def update_missing_report_status(
    request: Request,
    missing_report_id: int,
    report_status: MissingReportStatus,
    actor: AdminActorDependency,
    service: MissingReportServiceDependency,
) -> None:
    await service.update_status(actor=actor, missing_report_id=missing_report_id, status=report_status)


@router.patch("/{missing_report_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:missing-reports:detail",
    resource_id_name="missing_report_id",
    namespaces_to_invalidate=["admin:missing-reports"],
)
async def update_missing_report(
    request: Request,
    missing_report_id: int,
    payload: MissingReportUpdate,
    actor: AdminActorDependency,
    service: MissingReportServiceDependency,
) -> None:
    await service.update(actor=actor, missing_report_id=missing_report_id, report_input=payload)


@router.delete("/{missing_report_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:missing-reports:detail",
    resource_id_name="missing_report_id",
    namespaces_to_invalidate=["admin:missing-reports"],
)
async def hard_delete_missing_report(
    request: Request,
    missing_report_id: int,
    actor: SuperuserActorDependency,
    service: MissingReportServiceDependency,
) -> None:
    await service.hard_delete(actor=actor, missing_report_id=missing_report_id)
