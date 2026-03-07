from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import any_mobile_rate_limiter_dependency
from app.core.db.database import async_get_db
from app.core.schemas import Actor
from app.schemas.upload import SignedPostPolicyRequest, SignedPostPolicyResponse
from app.services.upload_service import UploadService

router = APIRouter(prefix="/uploads", tags=["Uploads"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> UploadService:
    return UploadService(db=db)


UploadServiceDependency = Annotated[UploadService, Depends(get_service)]
ActorDependency = Annotated[Actor, Depends(any_mobile_rate_limiter_dependency)]


@router.post("/signed-policies/images", response_model=SignedPostPolicyResponse, status_code=status.HTTP_200_OK)
async def generate_image_upload_policies(
    request: Request,
    payload: SignedPostPolicyRequest,
    actor: ActorDependency,
    service: UploadServiceDependency,
) -> SignedPostPolicyResponse:
    return await service.generate_image_upload_policies(actor=actor, filenames=payload.filenames)


@router.post("/signed-policies/documents", response_model=SignedPostPolicyResponse, status_code=status.HTTP_200_OK)
async def generate_document_upload_policies(
    request: Request,
    payload: SignedPostPolicyRequest,
    actor: ActorDependency,
    service: UploadServiceDependency,
) -> SignedPostPolicyResponse:
    return await service.generate_document_upload_policies(actor=actor, filenames=payload.filenames)
