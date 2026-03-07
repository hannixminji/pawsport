from typing import Annotated, Any, Union

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_authenticated_actor, guest_rate_limiter_dependency, rate_limiter_dependency
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

router = APIRouter(prefix="/sighting-reports", tags=["Sighting Reports"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> SightingReportService:
    return SightingReportService(db=db)


SightingReportServiceDependency = Annotated[SightingReportService, Depends(get_service)]
ActorDependency = Annotated[Actor, Depends(rate_limiter_dependency)]
AuthenticatedActorDependency = Annotated[Actor, Depends(get_current_authenticated_actor)]
GuestActorDependency = Annotated[Actor, Depends(guest_rate_limiter_dependency)]


@router.post("/viewport", response_model=list[dict[str, Any]], status_code=status.HTTP_200_OK)
async def get_combined_reports_by_viewport(
    viewport: MapViewport,
    actor: AuthenticatedActorDependency,
    service: SightingReportServiceDependency,
) -> list[dict[str, Any]]:
    return await service.get_combined_reports_by_viewport(viewport=viewport)


@router.post("/search", response_model=PaginatedResponse[SightingReportRead], status_code=status.HTTP_200_OK)
async def search_sighting_reports(
    search_request: SearchRequest,
    actor: ActorDependency,
    service: SightingReportServiceDependency,
) -> PaginatedResponse[SightingReportRead]:
    return await service.search(actor=actor, search_request=search_request, user_id=actor.id)


@router.post("", response_model=SightingReportRead, status_code=status.HTTP_201_CREATED)
async def create_sighting_report(
    request: Request,
    payload: SightingReportCreateWithImages,
    actor: GuestActorDependency,
    service: SightingReportServiceDependency,
) -> SightingReportRead:
    result = await service.create(actor=actor, user_id=actor.id, report_input=payload)
    await invalidate_namespace("sighting-reports")
    return result


@router.get("", response_model=PaginatedResponse[SightingReportRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:sighting-reports:list",
    resource_id_name=["page", "items_per_page", "actor.id"],
    namespace="sighting-reports",
    expiration=60,
)
async def list_sighting_reports(
    request: Request,
    actor: GuestActorDependency,
    service: SightingReportServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
) -> PaginatedResponse[SightingReportRead]:
    return await service.get_sighting_reports(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
        user_id=actor.id,
    )


@router.get(
    "/{report_id}",
    response_model=Union[SightingReportRead, SightingReportWithMatches],
    status_code=status.HTTP_200_OK,
)
@cache(
    key_prefix="app:sighting-reports:detail",
    resource_id_name=["report_id", "with_matches"],
    expiration=60,
)
async def get_sighting_report(
    request: Request,
    report_id: int,
    actor: GuestActorDependency,
    service: SightingReportServiceDependency,
    with_matches: Annotated[bool, Query(alias="withMatches")] = False,
) -> Union[SightingReportRead, SightingReportWithMatches]:
    return await service.get_sighting_report(actor=actor, report_id=report_id, with_matches=with_matches)


@router.patch("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="app:sighting-reports:detail",
    resource_id_name="report_id",
    namespaces_to_invalidate=["sighting-reports"],
)
async def update_sighting_report(
    request: Request,
    report_id: int,
    payload: SightingReportUpdateWithImages,
    actor: GuestActorDependency,
    service: SightingReportServiceDependency,
) -> None:
    await service.update(actor=actor, report_id=report_id, report_input=payload)
