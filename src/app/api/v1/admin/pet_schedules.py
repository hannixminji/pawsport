from typing import Annotated

from fastapi import Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter
from app.api.dependencies import get_current_admin_actor, get_current_superuser_actor
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.pet_schedule import (
    PetScheduleBulkDelete,
    PetScheduleCreate,
    PetScheduleRead,
    PetScheduleUpdate,
)
from app.services.pet_schedule_service import PetScheduleService

router = CSRFProtectedRouter(prefix="/schedules", tags=["Pet Schedules"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> PetScheduleService:
    return PetScheduleService(db=db)


PetScheduleServiceDependency = Annotated[PetScheduleService, Depends(get_service)]
SuperuserActorDependency = Annotated[Actor, Depends(get_current_superuser_actor)]
AdminActorDependency = Annotated[Actor, Depends(get_current_admin_actor)]


@router.post("/search", response_model=PaginatedResponse[PetScheduleRead], status_code=status.HTTP_200_OK)
async def search_pet_schedules(
    search_request: SearchRequest,
    actor: AdminActorDependency,
    service: PetScheduleServiceDependency,
    user_id: Annotated[int | None, Query(alias="userId")] = None,
    pet_id: Annotated[int | None, Query(alias="petId")] = None,
) -> PaginatedResponse[PetScheduleRead]:
    return await service.search(actor=actor, search_request=search_request, user_id=user_id, pet_id=pet_id)


@router.post("/{pet_id}", response_model=PetScheduleRead, status_code=status.HTTP_201_CREATED)
async def create_pet_schedule(
    request: Request,
    pet_id: int,
    payload: PetScheduleCreate,
    actor: AdminActorDependency,
    service: PetScheduleServiceDependency,
) -> PetScheduleRead:
    result = await service.create(actor=actor, pet_id=pet_id, schedule_input=payload)
    await invalidate_namespace("admin:pet-schedules")
    return result


@router.get("", response_model=PaginatedResponse[PetScheduleRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:pet-schedules:list",
    resource_id_name=["page", "items_per_page", "user_id", "pet_id"],
    namespace="admin:pet-schedules",
    expiration=60,
)
async def list_pet_schedules(
    request: Request,
    actor: AdminActorDependency,
    service: PetScheduleServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
    user_id: Annotated[int | None, Query(alias="userId")] = None,
    pet_id: Annotated[int | None, Query(alias="petId")] = None,
) -> PaginatedResponse[PetScheduleRead]:
    return await service.get_pet_schedules(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
        user_id=user_id,
        pet_id=pet_id,
    )


@router.get("/{schedule_id}", response_model=PetScheduleRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:pet-schedules:detail",
    resource_id_name="schedule_id",
    expiration=60,
)
async def get_pet_schedule(
    request: Request,
    schedule_id: int,
    actor: AdminActorDependency,
    service: PetScheduleServiceDependency,
) -> PetScheduleRead:
    return await service.get_pet_schedule(actor=actor, schedule_id=schedule_id)


@router.patch("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:pet-schedules:detail",
    resource_id_name="schedule_id",
    namespaces_to_invalidate=["admin:pet-schedules"],
)
async def update_pet_schedule(
    request: Request,
    schedule_id: int,
    payload: PetScheduleUpdate,
    actor: AdminActorDependency,
    service: PetScheduleServiceDependency,
) -> None:
    await service.update(actor=actor, schedule_id=schedule_id, schedule_input=payload)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_soft_delete_pet_schedules(
    payload: PetScheduleBulkDelete,
    actor: AdminActorDependency,
    service: PetScheduleServiceDependency,
) -> None:
    await service.bulk_soft_delete(actor=actor, schedule_ids=payload.ids)
    await invalidate_namespace("admin:pet-schedules")


@router.delete("/hard", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_hard_delete_pet_schedules(
    payload: PetScheduleBulkDelete,
    actor: SuperuserActorDependency,
    service: PetScheduleServiceDependency,
) -> None:
    await service.bulk_hard_delete(actor=actor, schedule_ids=payload.ids)
    await invalidate_namespace("admin:pet-schedules")


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:pet-schedules:detail",
    resource_id_name="schedule_id",
    namespaces_to_invalidate=["admin:pet-schedules"],
)
async def soft_delete_pet_schedule(
    request: Request,
    schedule_id: int,
    actor: AdminActorDependency,
    service: PetScheduleServiceDependency,
) -> None:
    await service.soft_delete(actor=actor, schedule_id=schedule_id)


@router.delete("/{schedule_id}/hard", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:pet-schedules:detail",
    resource_id_name="schedule_id",
    namespaces_to_invalidate=["admin:pet-schedules"],
)
async def hard_delete_pet_schedule(
    request: Request,
    schedule_id: int,
    actor: SuperuserActorDependency,
    service: PetScheduleServiceDependency,
) -> None:
    await service.hard_delete(actor=actor, schedule_id=schedule_id)
