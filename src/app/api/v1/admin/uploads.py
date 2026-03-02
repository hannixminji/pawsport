from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.csrf_router import CSRFProtectedRouter
from app.api.dependencies import get_current_admin_actor
from app.core.db.database import async_get_db
from app.core.schemas import Actor
from app.schemas.upload import SignedPostPolicyRequest, SignedPostPolicyResponse
from app.services.upload_service import UploadService

router = CSRFProtectedRouter(prefix="/uploads", tags=["Uploads"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> UploadService:
    return UploadService(db=db)


UploadServiceDependency = Annotated[UploadService, Depends(get_service)]
AdminActorDependency = Annotated[Actor, Depends(get_current_admin_actor)]


@router.post("/signed-policies", response_model=SignedPostPolicyResponse, status_code=status.HTTP_200_OK)
async def generate_signed_post_policies(
    request: Request,
    payload: SignedPostPolicyRequest,
    actor: AdminActorDependency,
    service: UploadServiceDependency,
) -> SignedPostPolicyResponse:
    return await service.generate_signed_post_policies(actor=actor, filenames=payload.filenames)
