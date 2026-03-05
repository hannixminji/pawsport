from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import rate_limiter_dependency
from app.core.db.database import async_get_db
from app.core.schemas import Actor
from app.core.utils.cache import cache
from app.schemas.pet_qr_default import PetQRDefaultRead, PetQRDefaultUpsert
from app.services.pet_qr_default_service import PetQRDefaultService

router = APIRouter(prefix="/qr-defaults", tags=["Pet QR Defaults"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> PetQRDefaultService:
    return PetQRDefaultService(db=db)


PetQRDefaultServiceDependency = Annotated[PetQRDefaultService, Depends(get_service)]
ActorDependency = Annotated[Actor, Depends(rate_limiter_dependency)]


@router.get("", response_model=PetQRDefaultRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:pet-qr-defaults:detail",
    resource_id_name="actor.id",
    expiration=60,
)
async def get_pet_qr_default(
    request: Request,
    actor: ActorDependency,
    service: PetQRDefaultServiceDependency,
) -> PetQRDefaultRead:
    return await service.get_default(actor=actor, owner_id=actor.id)


@router.put("", response_model=PetQRDefaultRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:pet-qr-defaults:detail",
    resource_id_name="actor.id",
)
async def upsert_pet_qr_default(
    request: Request,
    payload: PetQRDefaultUpsert,
    actor: ActorDependency,
    service: PetQRDefaultServiceDependency,
) -> PetQRDefaultRead:
    return await service.upsert(actor=actor, owner_id=actor.id, default_input=payload)
