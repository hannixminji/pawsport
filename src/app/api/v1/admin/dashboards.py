from typing import Annotated, Any

from fastapi import Depends, Request, status
from redis.asyncio import Redis

from app.api.csrf_router import CSRFProtectedRouter
from app.api.dependencies import require_permission
from app.core.utils.cache import async_get_redis, cache
from app.services.dashboard_service import DashboardService

router = CSRFProtectedRouter(prefix="/dashboards", tags=["Dashboards"])


def get_service(redis: Annotated[Redis | None, Depends(async_get_redis)]) -> DashboardService:
    return DashboardService(redis=redis)


DashboardServiceDependency = Annotated[DashboardService, Depends(get_service)]


@router.get("/stats", status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:dashboards:all_stats",
    namespace="admin:dashboards",
    expiration=60,
)
async def get_all_stats(
    request: Request,
    actor: Annotated[Any, Depends(require_permission("dashboard:read"))],
    service: DashboardServiceDependency,
) -> dict[str, Any]:
    return await service.get_all_stats()


@router.get("/mobile-users/stats", status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:dashboards:mobile_user_stats",
    namespace="admin:dashboards",
    expiration=60,
)
async def get_mobile_user_stats(
    request: Request,
    actor: Annotated[Any, Depends(require_permission("dashboard:read"))],
    service: DashboardServiceDependency,
) -> dict[str, Any]:
    return await service.get_mobile_user_stats()


@router.get("/pets/stats", status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:dashboards:pet_stats",
    namespace="admin:dashboards",
    expiration=60,
)
async def get_pet_stats(
    request: Request,
    actor: Annotated[Any, Depends(require_permission("dashboard:read"))],
    service: DashboardServiceDependency,
) -> dict[str, Any]:
    return await service.get_pet_stats()


@router.get("/pets/health/stats", status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:dashboards:pet_health_stats",
    namespace="admin:dashboards",
    expiration=60,
)
async def get_pet_health_stats(
    request: Request,
    actor: Annotated[Any, Depends(require_permission("dashboard:read"))],
    service: DashboardServiceDependency,
) -> dict[str, Any]:
    return await service.get_pet_health_stats()


@router.get("/pets/schedules/stats", status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:dashboards:pet_schedule_stats",
    namespace="admin:dashboards",
    expiration=60,
)
async def get_pet_schedule_stats(
    request: Request,
    actor: Annotated[Any, Depends(require_permission("dashboard:read"))],
    service: DashboardServiceDependency,
) -> dict[str, Any]:
    return await service.get_pet_schedule_stats()


@router.get("/pets/inventory/stats", status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:dashboards:pet_inventory_stats",
    namespace="admin:dashboards",
    expiration=60,
)
async def get_pet_inventory_stats(
    request: Request,
    actor: Annotated[Any, Depends(require_permission("dashboard:read"))],
    service: DashboardServiceDependency,
) -> dict[str, Any]:
    return await service.get_pet_inventory_stats()


@router.get("/pets/{pet_id}/stats", status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:dashboards:pet_detail_stats",
    resource_id_name="pet_id",
    namespace="admin:dashboards",
    expiration=60,
)
async def get_pet_detail_stats(
    request: Request,
    pet_id: int,
    actor: Annotated[Any, Depends(require_permission("dashboard:read"))],
    service: DashboardServiceDependency,
) -> dict[str, Any]:
    return await service.get_pet_detail_stats(pet_id=pet_id)


@router.get("/missing-reports/stats", status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:dashboards:missing_report_stats",
    namespace="admin:dashboards",
    expiration=60,
)
async def get_missing_report_stats(
    request: Request,
    actor: Annotated[Any, Depends(require_permission("dashboard:read"))],
    service: DashboardServiceDependency,
) -> dict[str, Any]:
    return await service.get_missing_report_stats()


@router.get("/sighting-reports/stats", status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:dashboards:sighting_report_stats",
    namespace="admin:dashboards",
    expiration=60,
)
async def get_sighting_report_stats(
    request: Request,
    actor: Annotated[Any, Depends(require_permission("dashboard:read"))],
    service: DashboardServiceDependency,
) -> dict[str, Any]:
    return await service.get_sighting_report_stats()


@router.get("/articles/stats", status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:dashboards:article_stats",
    namespace="admin:dashboards",
    expiration=60,
)
async def get_article_stats(
    request: Request,
    actor: Annotated[Any, Depends(require_permission("dashboard:read"))],
    service: DashboardServiceDependency,
) -> dict[str, Any]:
    return await service.get_article_stats()


@router.get("/admin-users/stats", status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:dashboards:admin_user_stats",
    namespace="admin:dashboards",
    expiration=60,
)
async def get_admin_user_stats(
    request: Request,
    actor: Annotated[Any, Depends(require_permission("dashboard:read"))],
    service: DashboardServiceDependency,
) -> dict[str, Any]:
    return await service.get_admin_user_stats()


@router.get("/tiers/stats", status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:dashboards:tier_stats",
    namespace="admin:dashboards",
    expiration=60,
)
async def get_tier_stats(
    request: Request,
    actor: Annotated[Any, Depends(require_permission("dashboard:read"))],
    service: DashboardServiceDependency,
) -> list[dict[str, Any]]:
    return await service.get_tier_stats()


@router.get("/health", status_code=status.HTTP_200_OK)
async def get_health(
    actor: Annotated[Any, Depends(require_permission("dashboard:read"))],
    service: DashboardServiceDependency,
) -> dict[str, Any]:
    return await service.get_health()


@router.get("/users/{user_id}/stats", status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:dashboards:user_stats",
    resource_id_name="user_id",
    namespace="admin:dashboards",
    expiration=60,
)
async def get_user_stats(
    request: Request,
    user_id: int,
    actor: Annotated[Any, Depends(require_permission("dashboard:read"))],
    service: DashboardServiceDependency,
) -> dict[str, Any]:
    return await service.get_user_stats(user_id=user_id)
