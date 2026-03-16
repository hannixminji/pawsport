from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ip_rate_limit_dependency, rate_limiter_dependency
from app.core.db.database import async_get_db
from app.core.enums import AuthProvider
from app.core.schemas import Actor
from app.core.security import security
from app.core.utils.cache import cache
from app.schemas.mobile_user import (
    MobileUserAddEmailPassword,
    MobileUserEmailChangeOtpVerify,
    MobileUserEmailChangeOtpVerifyRead,
    MobileUserEmailChangeRequest,
    MobileUserLinkedProvidersRead,
    MobileUserPasswordUpdate,
    MobileUserRead,
    MobileUserRemoveLinkedProvider,
    MobileUserUpdate,
)
from app.services.mobile_user_service import MobileUserService

router = APIRouter(prefix="/mobile-users", tags=["Mobile Users"])


def _static_html_response(html_content: str) -> HTMLResponse:
    response = HTMLResponse(content=html_content)
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; "
        "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
        "font-src https://fonts.gstatic.com; "
        "script-src 'none'; "
        "img-src 'self' data: https://storage.googleapis.com; "
        "base-uri 'none'; "
        "form-action 'none'; "
        "frame-ancestors 'none';"
    )
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> MobileUserService:
    return MobileUserService(db=db)


MobileUserServiceDependency = Annotated[MobileUserService, Depends(get_service)]
ActorDependency = Annotated[Actor, Depends(rate_limiter_dependency)]
IpRateLimitDependency = Depends(ip_rate_limit_dependency)


@router.get("/verify-email", response_class=HTMLResponse, status_code=status.HTTP_200_OK)
async def verify_email_from_link(
    token: Annotated[str, Query()],
    service: MobileUserServiceDependency,
    _: Annotated[None, IpRateLimitDependency],
) -> HTMLResponse:
    await service.verify_email(raw_token=token)
    return _static_html_response(service.render_template("email_verified.html"))


@router.get("/me", response_model=MobileUserRead, status_code=status.HTTP_200_OK)
@cache(
    key_prefix="app:mobile-users:detail",
    resource_id_name="actor.id",
    expiration=60,
)
async def get_mobile_user(
    request: Request,
    actor: ActorDependency,
    service: MobileUserServiceDependency,
) -> MobileUserRead:
    return await service.get_mobile_user(actor=actor, user_id=actor.id)


@router.get("/me/providers", response_model=MobileUserLinkedProvidersRead, status_code=status.HTTP_200_OK)
async def get_mobile_user_linked_providers(
    request: Request,
    actor: ActorDependency,
    service: MobileUserServiceDependency,
) -> MobileUserLinkedProvidersRead:
    return await service.get_linked_providers(actor=actor, user_id=actor.id)


@router.post("/email/verification", status_code=status.HTTP_204_NO_CONTENT)
async def send_verification_email(
    request: Request,
    actor: ActorDependency,
    service: MobileUserServiceDependency,
) -> None:
    await service.send_verification_email(
        actor=actor,
        user_id=actor.id,
    )


@router.post("/email/change/request-otp", status_code=status.HTTP_204_NO_CONTENT)
async def request_email_change_otp(
    request: Request,
    actor: ActorDependency,
    service: MobileUserServiceDependency,
) -> None:
    await service.request_email_change_otp(
        actor=actor,
        user_id=actor.id,
    )


@router.post(
    "/email/change/verify-otp",
    response_model=MobileUserEmailChangeOtpVerifyRead,
    status_code=status.HTTP_200_OK,
)
async def verify_email_change_otp(
    request: Request,
    payload: MobileUserEmailChangeOtpVerify,
    actor: ActorDependency,
    service: MobileUserServiceDependency,
) -> MobileUserEmailChangeOtpVerifyRead:
    return await service.verify_email_change_otp(
        actor=actor,
        user_id=actor.id,
        otp=payload.otp,
    )


@router.post("/email/change", status_code=status.HTTP_204_NO_CONTENT)
async def request_email_change(
    request: Request,
    payload: MobileUserEmailChangeRequest,
    actor: ActorDependency,
    service: MobileUserServiceDependency,
) -> None:
    await service.request_email_change(
        actor=actor,
        user_id=actor.id,
        authorization_token=payload.authorization_token,
        new_email=payload.new_email,
        current_password=payload.current_password.get_secret_value() if payload.current_password else None,
    )


@router.get("/email/verify-new", response_class=HTMLResponse, status_code=status.HTTP_200_OK)
async def verify_new_email_from_link(
    token: Annotated[str, Query()],
    service: MobileUserServiceDependency,
    _: Annotated[None, IpRateLimitDependency],
) -> HTMLResponse:
    await service.verify_new_email(raw_token=token)
    return _static_html_response(service.render_template("email_change_verified.html"))


@router.post("/me/providers/email", status_code=status.HTTP_204_NO_CONTENT)
async def add_email_password(
    request: Request,
    payload: MobileUserAddEmailPassword,
    actor: ActorDependency,
    service: MobileUserServiceDependency,
) -> None:
    await service.add_email_password(
        actor=actor,
        user_id=actor.id,
        email=payload.email,
        password=payload.password.get_secret_value(),
    )


@router.post("/me/providers/google", status_code=status.HTTP_204_NO_CONTENT)
async def add_google(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    actor: ActorDependency,
    service: MobileUserServiceDependency,
) -> None:
    await service.add_google(
        actor=actor,
        user_id=actor.id,
        token=credentials.credentials,
    )


@router.post("/me/providers/{provider}/remove", status_code=status.HTTP_204_NO_CONTENT)
async def remove_linked_provider(
    request: Request,
    provider: AuthProvider,
    payload: MobileUserRemoveLinkedProvider,
    actor: ActorDependency,
    service: MobileUserServiceDependency,
) -> None:
    await service.remove_linked_provider(
        actor=actor,
        user_id=actor.id,
        provider=provider,
        current_password=payload.current_password.get_secret_value() if payload.current_password else None,
    )


@router.patch("/me", status_code=status.HTTP_204_NO_CONTENT)
@cache(
    key_prefix="app:mobile-users:detail",
    resource_id_name="actor.id",
    namespaces_to_invalidate=["mobile-users"],
)
async def update_mobile_user(
    request: Request,
    payload: MobileUserUpdate,
    actor: ActorDependency,
    service: MobileUserServiceDependency,
) -> None:
    await service.update(actor=actor, user_id=actor.id, user_input=payload)


@router.patch("/password", status_code=status.HTTP_204_NO_CONTENT)
async def update_mobile_user_password(
    request: Request,
    payload: MobileUserPasswordUpdate,
    actor: ActorDependency,
    service: MobileUserServiceDependency,
) -> None:
    await service.change_password(
        actor=actor,
        user_id=actor.id,
        current_password=payload.current_password.get_secret_value(),
        new_password=payload.new_password.get_secret_value(),
    )

@router.patch("/me/delete", status_code=status.HTTP_204_NO_CONTENT)
async def soft_delete_mobile_user(
    request: Request,
    actor: ActorDependency,
    service: MobileUserServiceDependency,
) -> None:
    await service.soft_delete(actor=actor, user_id=actor.id)
