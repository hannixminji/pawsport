from typing import Annotated, Any, Union

from fastapi import Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter
from app.api.dependencies import get_current_admin_actor, get_current_superuser_actor
from app.core.db.database import async_get_db
from app.core.schemas import Actor, MapViewport, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.sighting_report import (
    SightingReportCreateWithImages,
    SightingReportRead,
    SightingReportUpdateWithImages,
    SightingReportWithMatches,
)
from app.services.sighting_report_service import SightingReportService

router = CSRFProtectedRouter(prefix="/sighting-reports", tags=["Sighting Reports"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> SightingReportService:
    return SightingReportService(db=db)


SightingReportServiceDependency = Annotated[SightingReportService, Depends(get_service)]
SuperuserActorDependency = Annotated[Actor, Depends(get_current_superuser_actor)]
AdminActorDependency = Annotated[Actor, Depends(get_current_admin_actor)]


@router.post("/{user_id}", response_model=SightingReportRead, status_code=status.HTTP_201_CREATED)
async def create_sighting_report(
    request: Request,
    user_id: int,
    payload: SightingReportCreateWithImages,
    actor: AdminActorDependency,
    service: SightingReportServiceDependency,
) -> SightingReportRead:
    result = await service.create(actor=actor, user_id=user_id, report_input=payload)
    await invalidate_namespace("admin:sighting-reports")
    return result


@router.post("/viewport", response_model=list[dict[str, Any]], status_code=status.HTTP_200_OK)
async def get_combined_reports_by_viewport(
    viewport: MapViewport,
    service: SightingReportServiceDependency,
) -> list[dict[str, Any]]:
    return await service.get_combined_reports_by_viewport(viewport=viewport)


@router.post("/search", response_model=PaginatedResponse[SightingReportRead], status_code=status.HTTP_200_OK)
async def search_sighting_reports(
    search_request: SearchRequest,
    actor: AdminActorDependency,
    service: SightingReportServiceDependency,
    user_id: Annotated[int | None, Query(alias="userId")] = None,
) -> PaginatedResponse[SightingReportRead]:
    return await service.search(actor=actor, search_request=search_request, user_id=user_id)


@router.get("", response_model=PaginatedResponse[SightingReportRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:sighting-reports:list",
    resource_id_name=["page", "items_per_page", "user_id"],
    namespace="admin:sighting-reports",
    expiration=60,
)
async def list_sighting_reports(
    request: Request,
    actor: AdminActorDependency,
    service: SightingReportServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
    user_id: Annotated[int | None, Query(alias="userId")] = None,
) -> PaginatedResponse[SightingReportRead]:
    return await service.get_sighting_reports(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
        user_id=user_id,
    )


@router.get(
    "/{report_id}",
    response_model=Union[SightingReportRead, SightingReportWithMatches],
    status_code=status.HTTP_200_OK
)
@cache(
    key_prefix="admin:sighting-reports:detail",
    resource_id_name="report_id",
    expiration=60,
)
async def get_sighting_report(
    request: Request,
    report_id: int,
    actor: AdminActorDependency,
    service: SightingReportServiceDependency,
    with_matches: Annotated[bool, Query(alias="withMatches")] = False,
) -> Union[SightingReportRead, SightingReportWithMatches]:
    return await service.get_sighting_report(actor=actor, report_id=report_id, with_matches=with_matches)


@router.patch("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:sighting-reports:detail",
    resource_id_name="report_id",
    namespaces_to_invalidate=["admin:sighting-reports"],
)
async def update_sighting_report(
    request: Request,
    report_id: int,
    payload: SightingReportUpdateWithImages,
    actor: AdminActorDependency,
    service: SightingReportServiceDependency,
) -> None:
    await service.update(actor=actor, report_id=report_id, report_input=payload)


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:sighting-reports:detail",
    resource_id_name="report_id",
    namespaces_to_invalidate=["admin:sighting-reports"],
)
async def soft_delete_sighting_report(
    request: Request,
    report_id: int,
    actor: AdminActorDependency,
    service: SightingReportServiceDependency,
) -> None:
    await service.soft_delete(actor=actor, report_id=report_id)


@router.delete("/{report_id}/hard", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:sighting-reports:detail",
    resource_id_name="report_id",
    namespaces_to_invalidate=["admin:sighting-reports"],
)
async def hard_delete_sighting_report(
    request: Request,
    report_id: int,
    actor: SuperuserActorDependency,
    service: SightingReportServiceDependency,
) -> None:
    await service.hard_delete(actor=actor, report_id=report_id)
