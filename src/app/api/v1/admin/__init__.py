from fastapi import APIRouter

from .auth import router as auth_router
from .permissions import router as permission_router

router = APIRouter(prefix="/admin")
router.include_router(auth_router)
router.include_router(permission_router)
