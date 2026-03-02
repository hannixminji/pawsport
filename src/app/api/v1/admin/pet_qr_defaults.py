from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter
from app.api.dependencies import get_current_admin_actor
from app.core.db.database import async_get_db
from app.core.schemas import Actor
from app.core.utils.cache import cache
from app.schemas.pet_qr_default import PetQRDefaultRead, PetQRDefaultUpsert
from app.services.pet_qr_default_service import PetQRDefaultService

router = CSRFProtectedRouter(prefix="/qr-defaults", tags=["Pet QR Defaults"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> PetQRDefaultService:
    return PetQRDefaultService(db=db)


PetQRDefaultServiceDependency = Annotated[PetQRDefaultService, Depends(get_service)]
AdminActorDependency = Annotated[Actor, Depends(get_current_admin_actor)]


@router.get("/{owner_id}", response_model=PetQRDefaultRead, status_code=status.HTTP_200_OK)
@cache(key_prefix="pet_qr_default", resource_id_name="owner_id", expiration=60)
async def get_pet_qr_default(
    request: Request,
    owner_id: int,
    actor: AdminActorDependency,
    service: PetQRDefaultServiceDependency,
) -> PetQRDefaultRead:
    return await service.get_default(actor=actor, owner_id=owner_id)


@router.put("/{owner_id}", response_model=PetQRDefaultRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="pet_qr_default",
    resource_id_name="owner_id",
    pattern_to_invalidate_extra=["pet_qr_default:*"],
)
async def upsert_pet_qr_default(
    request: Request,
    owner_id: int,
    payload: PetQRDefaultUpsert,
    actor: AdminActorDependency,
    service: PetQRDefaultServiceDependency,
) -> PetQRDefaultRead:
    return await service.upsert(actor=actor, owner_id=owner_id, default_input=payload)
