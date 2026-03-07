from typing import Annotated

from fastapi import Depends, File, Form, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter, csrf_exempt
from app.api.dependencies import get_current_superuser_actor, require_permission
from app.core.db.database import async_get_db
from app.core.enums import PetSpecies
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.pet import PetCreateWithPhotos, PetRead, PetSearch, PetUpdateWithPhotos
from app.services.pet_service import PetService

router = CSRFProtectedRouter(prefix="/pets", tags=["Pets"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> PetService:
    return PetService(db=db)


PetServiceDependency = Annotated[PetService, Depends(get_service)]
SuperuserActorDependency = Annotated[Actor, Depends(get_current_superuser_actor)]


@csrf_exempt
@router.post("/search/image", response_model=list[PetSearch], status_code=status.HTTP_200_OK)
async def search_pets_by_image(
    actor: Annotated[Actor, Depends(require_permission("pet:search"))],
    service: PetServiceDependency,
    file: Annotated[UploadFile, File()],
    species: Annotated[PetSpecies, Form()],
    is_search_by_missing: Annotated[bool | None, Form(alias="isSearchByMissing")] = None,
) -> list[PetSearch]:
    file_content = await file.read()
    return await service.search_by_image(
        file_content=file_content,
        filename=file.filename,
        content_type=file.content_type,
        species=species,
        is_search_by_missing=is_search_by_missing,
    )


@csrf_exempt
@router.post("/search", response_model=PaginatedResponse[PetRead], status_code=status.HTTP_200_OK)
async def search_pets(
    search_request: SearchRequest,
    actor: Annotated[Actor, Depends(require_permission("pet:search"))],
    service: PetServiceDependency,
    user_id: Annotated[int | None, Query(alias="userId")] = None,
) -> PaginatedResponse[PetRead]:
    return await service.search(actor=actor, search_request=search_request, user_id=user_id)


@router.post("/{user_id}", response_model=PetRead, status_code=status.HTTP_201_CREATED)
async def create_pet(
    request: Request,
    user_id: int,
    payload: PetCreateWithPhotos,
    actor: Annotated[Actor, Depends(require_permission("pet:create"))],
    service: PetServiceDependency,
) -> PetRead:
    result = await service.create(actor=actor, user_id=user_id, pet_input=payload)
    await invalidate_namespace("pets")
    return result


@router.get("", response_model=PaginatedResponse[PetRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:pets:list",
    resource_id_name=["page", "items_per_page", "user_id"],
    namespace="pets",
    expiration=60,
)
async def list_pets(
    request: Request,
    actor: Annotated[Actor, Depends(require_permission("pet:read"))],
    service: PetServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
    user_id: Annotated[int | None, Query(alias="userId")] = None,
) -> PaginatedResponse[PetRead]:
    return await service.get_pets(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
        user_id=user_id,
    )


@router.get("/{pet_id}", response_model=PetRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="admin:pets:detail",
    resource_id_name="pet_id",
    expiration=60,
)
async def get_pet(
    request: Request,
    pet_id: int,
    actor: Annotated[Actor, Depends(require_permission("pet:read"))],
    service: PetServiceDependency,
) -> PetRead:
    return await service.get_pet(actor=actor, pet_id=pet_id)


@router.patch("/{pet_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:pets:detail",
    resource_id_name="pet_id",
    namespaces_to_invalidate=["pets"],
)
async def soft_delete_pet(
    request: Request,
    pet_id: int,
    actor: Annotated[Actor, Depends(require_permission("pet:soft_delete"))],
    service: PetServiceDependency,
) -> None:
    await service.soft_delete(actor=actor, pet_id=pet_id)


@router.patch("/{pet_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:pets:detail",
    resource_id_name="pet_id",
    namespaces_to_invalidate=["pets"],
)
async def update_pet(
    request: Request,
    pet_id: int,
    payload: PetUpdateWithPhotos,
    actor: Annotated[Actor, Depends(require_permission("pet:update"))],
    service: PetServiceDependency,
) -> None:
    await service.update(actor=actor, pet_id=pet_id, pet_input=payload)


@router.delete("/{pet_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="admin:pets:detail",
    resource_id_name="pet_id",
    namespaces_to_invalidate=["pets"],
)
async def hard_delete_pet(
    request: Request,
    pet_id: int,
    actor: SuperuserActorDependency,
    service: PetServiceDependency,
) -> None:
    await service.hard_delete(actor=actor, pet_id=pet_id)
