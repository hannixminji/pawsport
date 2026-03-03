from datetime import date
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.database import async_get_db
from app.services.pet_service import PetService

TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "core" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

router = APIRouter(prefix="/pets", tags=["Pets"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> PetService:
    return PetService(db=db)


PetServiceDependency = Annotated[PetService, Depends(get_service)]


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

    return templates.TemplateResponse(
        "pet_qr.html",
        {
            "request": request,
            "pet": pet.model_dump(mode="python"),
            "today": date.today(),
        },
    )
