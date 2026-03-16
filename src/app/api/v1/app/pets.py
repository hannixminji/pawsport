import secrets
from datetime import date
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import rate_limiter_dependency
from app.core.db.database import async_get_db
from app.core.enums import PetSpecies
from app.core.schemas import Actor, PaginatedResponse
from app.core.search_engine.schemas import SearchRequest
from app.core.utils.cache import cache, invalidate_namespace
from app.schemas.pet import PetCreateWithPhotos, PetRead, PetSearch, PetUpdateWithPhotos
from app.services.pet_service import PetService

TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "core" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

router = APIRouter(prefix="/pets", tags=["Pets"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> PetService:
    return PetService(db=db)


PetServiceDependency = Annotated[PetService, Depends(get_service)]
ActorDependency = Annotated[Actor, Depends(rate_limiter_dependency)]


@router.post("/search/image", response_model=list[PetSearch], status_code=status.HTTP_200_OK)
async def search_pets_by_image(
    actor: ActorDependency,
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


@router.post("/search", response_model=PaginatedResponse[PetRead], status_code=status.HTTP_200_OK)
async def search_pets(
    search_request: SearchRequest,
    actor: ActorDependency,
    service: PetServiceDependency,
) -> PaginatedResponse[PetRead]:
    return await service.search(actor=actor, search_request=search_request, user_id=actor.id)


@router.post("", response_model=PetRead, status_code=status.HTTP_201_CREATED)
async def create_pet(
    request: Request,
    payload: PetCreateWithPhotos,
    actor: ActorDependency,
    service: PetServiceDependency,
) -> PetRead:
    result = await service.create(actor=actor, user_id=actor.id, pet_input=payload)
    await invalidate_namespace("pets")
    return result


@router.get("", response_model=PaginatedResponse[PetRead], status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:pets:list",
    resource_id_name=["page", "items_per_page", "actor.id"],
    namespace="pets",
    expiration=60,
)
async def list_pets(
    request: Request,
    actor: ActorDependency,
    service: PetServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    items_per_page: Annotated[int, Query(ge=1, le=100, alias="itemsPerPage")] = 10,
) -> PaginatedResponse[PetRead]:
    return await service.get_pets(
        actor=actor,
        page=page,
        items_per_page=items_per_page,
        user_id=actor.id,
    )


@router.get("/qr/{pet_uuid}", response_model=None, response_class=HTMLResponse, status_code=status.HTTP_200_OK)
async def get_pet_by_qr(
    request: Request,
    pet_uuid: UUID,
    service: PetServiceDependency,
) -> HTMLResponse | JSONResponse:
    pet = await service.get_pet_by_qr(pet_uuid=pet_uuid)

    accept = (request.headers.get("accept") or "").lower()

    if "application/json" in accept:
        return JSONResponse(content=pet.model_dump(mode="json"))

    csp_nonce = secrets.token_urlsafe(32)
    response = templates.TemplateResponse(
        "pet_qr.html",
        {
            "request": request,
            "pet": pet,
            "today": date.today(),
            "csp_nonce": csp_nonce,
        },
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; "
        f"script-src 'nonce-{csp_nonce}'; "
        "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
        "font-src https://fonts.gstatic.com; "
        "connect-src 'self'; "
        "img-src 'self' https: data:; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none';"
    )
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/{pet_id}", response_model=PetRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:pets:detail",
    resource_id_name="pet_id",
    expiration=60,
)
async def get_pet(
    request: Request,
    pet_id: int,
    actor: ActorDependency,
    service: PetServiceDependency,
) -> PetRead:
    return await service.get_pet(actor=actor, pet_id=pet_id)


@router.patch("/{pet_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="app:pets:detail",
    resource_id_name="pet_id",
    namespaces_to_invalidate=["pets"],
)
async def soft_delete_pet(
    request: Request,
    pet_id: int,
    actor: ActorDependency,
    service: PetServiceDependency,
) -> None:
    await service.soft_delete(actor=actor, pet_id=pet_id)


@router.patch("/{pet_id}", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="app:pets:detail",
    resource_id_name="pet_id",
    namespaces_to_invalidate=["pets"],
)
async def update_pet(
    request: Request,
    pet_id: int,
    payload: PetUpdateWithPhotos,
    actor: ActorDependency,
    service: PetServiceDependency,
) -> None:
    await service.update(actor=actor, pet_id=pet_id, pet_input=payload)
