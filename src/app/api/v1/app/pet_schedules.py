from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import rate_limiter_dependency
from app.core.db.database import async_get_db
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.pet_schedule import PetScheduleCreate, PetScheduleRead, PetScheduleUpdate
from app.services.pet_schedule_service import PetScheduleService

router = APIRouter(prefix="/schedules", tags=["Pet Schedules"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> PetScheduleService:
    return PetScheduleService(db=db)


PetScheduleServiceDependency = Annotated[PetScheduleService, Depends(get_service)]
ActorDependency = Annotated[Actor, Depends(rate_limiter_dependency)]


@router.post("/search", response_model=PaginatedResponse[PetScheduleRead], status_code=status.HTTP_200_OK)
async def search_pet_schedules(
    search_request: SearchRequest,
    actor: ActorDependency,
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
    actor: ActorDependency,
    service: PetScheduleServiceDependency,
) -> PetScheduleRead:
    result = await service.create(actor=actor, pet_id=pet_id, schedule_input=payload)
    await invalidate_namespace("app:pet-schedules")
    return result


@router.get("", response_model=PaginatedResponse[PetScheduleRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:pet-schedules:list",
    resource_id_name=["page", "items_per_page", "user_id", "pet_id"],
    namespace="app:pet-schedules",
    expiration=60,
)
async def list_pet_schedules(
    request: Request,
    actor: ActorDependency,
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
    key_prefix="app:pet-schedules:detail",
    resource_id_name="schedule_id",
    expiration=60,
)
async def get_pet_schedule(
    request: Request,
    schedule_id: int,
    actor: ActorDependency,
    service: PetScheduleServiceDependency,
) -> PetScheduleRead:
    return await service.get_pet_schedule(actor=actor, schedule_id=schedule_id)


@router.patch("/{schedule_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="app:pet-schedules:detail",
    resource_id_name="schedule_id",
    namespaces_to_invalidate=["app:pet-schedules"],
)
async def soft_delete_pet_schedule(
    request: Request,
    schedule_id: int,
    actor: ActorDependency,
    service: PetScheduleServiceDependency,
) -> None:
    await service.soft_delete(actor=actor, schedule_id=schedule_id)


@router.patch("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="app:pet-schedules:detail",
    resource_id_name="schedule_id",
    namespaces_to_invalidate=["app:pet-schedules"],
)
async def update_pet_schedule(
    request: Request,
    schedule_id: int,
    payload: PetScheduleUpdate,
    actor: ActorDependency,
    service: PetScheduleServiceDependency,
) -> None:
    await service.update(actor=actor, schedule_id=schedule_id, schedule_input=payload)
