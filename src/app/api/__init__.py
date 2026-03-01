from fastapi import APIRouter, Depends

from app.api.v1.admin import router as admin_router
from app.api.v1.app import router as app_router

router = APIRouter(prefix="/api/v1")
router.include_router(admin_router)
router.include_router(app_router)
