from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import rate_limiter_dependency
from app.core.db.database import async_get_db
from app.core.enums import MobileMissingReportStatus
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.missing_report import MissingReportCreate, MissingReportRead, MissingReportUpdate
from app.services.missing_report_service import MissingReportService

router = APIRouter(prefix="/missing-reports", tags=["Missing Reports"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> MissingReportService:
    return MissingReportService(db=db)


MissingReportServiceDependency = Annotated[MissingReportService, Depends(get_service)]
ActorDependency = Annotated[Actor, Depends(rate_limiter_dependency)]


@router.post("/search", response_model=PaginatedResponse[MissingReportRead], status_code=status.HTTP_200_OK)
async def search_missing_reports(
    search_request: SearchRequest,
    actor: ActorDependency,
    service: MissingReportServiceDependency,
    pet_id: Annotated[int | None, Query(alias="petId")] = None,
) -> PaginatedResponse[MissingReportRead]:
    return await service.search(actor=actor, search_request=search_request, user_id=actor.id, pet_id=pet_id)


@router.post("/{pet_id}", response_model=MissingReportRead, status_code=status.HTTP_201_CREATED)
async def create_missing_report(
    request: Request,
    pet_id: int,
    payload: MissingReportCreate,
    actor: ActorDependency,
    service: MissingReportServiceDependency,
) -> MissingReportRead:
    result = await service.create(actor=actor, pet_id=pet_id, report_input=payload)
    await invalidate_namespace("app:missing-reports")
    return result


@router.get("", response_model=PaginatedResponse[MissingReportRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:missing-reports:list",
    resource_id_name=["page", "items_per_page", "pet_id"],
    namespace="app:missing-reports",
    expiration=60,
)
async def list_missing_reports(
    request: Request,
    actor: ActorDependency,
    service: MissingReportServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
    pet_id: Annotated[int | None, Query(alias="petId")] = None,
) -> PaginatedResponse[MissingReportRead]:
    return await service.get_missing_reports(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
        user_id=actor.id,
        pet_id=pet_id,
    )


@router.get("/{missing_report_id}", response_model=MissingReportRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:missing-reports:detail",
    resource_id_name="missing_report_id",
    expiration=60,
)
async def get_missing_report(
    request: Request,
    missing_report_id: int,
    actor: ActorDependency,
    service: MissingReportServiceDependency,
) -> MissingReportRead:
    return await service.get_missing_report(actor=actor, missing_report_id=missing_report_id)


@router.patch("/{missing_report_id}/status", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="app:missing-reports:detail",
    resource_id_name="missing_report_id",
    namespaces_to_invalidate=["app:missing-reports"],
)
async def update_missing_report_status(
    request: Request,
    missing_report_id: int,
    report_status: MobileMissingReportStatus,
    actor: ActorDependency,
    service: MissingReportServiceDependency,
) -> None:
    await service.update_status(actor=actor, missing_report_id=missing_report_id, status=report_status)


@router.patch("/{missing_report_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="app:missing-reports:detail",
    resource_id_name="missing_report_id",
    namespaces_to_invalidate=["app:missing-reports"],
)
async def update_missing_report(
    request: Request,
    missing_report_id: int,
    payload: MissingReportUpdate,
    actor: ActorDependency,
    service: MissingReportServiceDependency,
) -> None:
    await service.update(actor=actor, missing_report_id=missing_report_id, report_input=payload)
