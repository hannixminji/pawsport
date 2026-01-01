from fastapi import APIRouter

from .login import router as login_or_signup_router

router = APIRouter(prefix="/v2")
router.include_router(login_or_signup_router)
