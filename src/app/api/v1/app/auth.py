import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_mobile_user, ip_rate_limit_dependency
from app.core.db.database import async_get_db
from app.core.security import security
from app.schemas.mobile_user import (
    MobileActor,
    MobileUserEmailPasswordLogin,
    MobileUserEmailPasswordRegister,
    MobileUserForgotPassword,
    MobileUserRead,
    MobileUserResetPassword,
)
from app.schemas.token import TokenResponse
from app.services.mobile_user_service import MobileUserService

router = APIRouter(prefix="/auth", tags=["login or signup"])


def get_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> MobileUserService:
    return MobileUserService(db=db)


MobileUserServiceDependency = Annotated[MobileUserService, Depends(get_service)]
IpRateLimitDependency = Depends(ip_rate_limit_dependency)


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: Request,
    payload: MobileUserEmailPasswordRegister,
    service: MobileUserServiceDependency,
    _: Annotated[None, IpRateLimitDependency],
) -> TokenResponse:
    return await service.register(payload=payload)


@router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def login(
    request: Request,
    payload: MobileUserEmailPasswordLogin,
    service: MobileUserServiceDependency,
    _: Annotated[None, IpRateLimitDependency],
) -> TokenResponse:
    return await service.login(payload=payload)


@router.post("/google", response_model=MobileUserRead, status_code=status.HTTP_200_OK)
async def login_or_signup(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    service: MobileUserServiceDependency,
    _: Annotated[None, IpRateLimitDependency],
) -> MobileUserRead:
    return await service.login_or_signup_google(token=credentials.credentials)


@router.post("/guest", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def guest_login(
    request: Request,
    service: MobileUserServiceDependency,
    _: Annotated[None, IpRateLimitDependency],
) -> TokenResponse:
    return await service.guest_login()


@router.post("/refresh", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def refresh(
    request: Request,
    body: RefreshTokenRequest,
    service: MobileUserServiceDependency,
    _: Annotated[None, IpRateLimitDependency],
) -> TokenResponse:
    return await service.refresh_token(refresh_token=body.refresh_token)


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    request: Request,
    body: LogoutRequest,
    service: MobileUserServiceDependency,
    _current_user: Annotated[MobileActor, Depends(get_current_mobile_user)],
    _: Annotated[None, IpRateLimitDependency],
) -> dict[str, str]:
    return await service.logout(refresh_token=body.refresh_token)


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(
    request: Request,
    payload: MobileUserForgotPassword,
    service: MobileUserServiceDependency,
    _: Annotated[None, IpRateLimitDependency],
) -> None:
    await service.forgot_password(email=payload.email)


@router.get("/reset-password", response_class=HTMLResponse, status_code=status.HTTP_200_OK)
async def reset_password_page(
    request: Request,
    token: str,
    service: MobileUserServiceDependency,
    _: Annotated[None, IpRateLimitDependency],
) -> HTMLResponse:
    await service.validate_password_reset_token(raw_token=token)
    csp_nonce = secrets.token_urlsafe(32)
    content = service.render_template("password_reset_form.html", token=token, csp_nonce=csp_nonce)
    response = HTMLResponse(content=content)
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; "
        f"script-src 'nonce-{csp_nonce}'; "
        "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
        "font-src https://fonts.gstatic.com; "
        "connect-src 'self'; "
        "img-src 'self' data:; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none';"
    )
    return response


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    request: Request,
    payload: MobileUserResetPassword,
    service: MobileUserServiceDependency,
    _: Annotated[None, IpRateLimitDependency],
) -> None:
    await service.reset_password(
        raw_token=payload.token,
        new_password=payload.new_password.get_secret_value(),
    )
