from fastapi import APIRouter

from .gcs_signed_url import router as gcs_signed_url_router
from .health import router as health_router
from .login import router as login_router
from .logout import router as logout_router
from .missing_reports import router as missing_reports_router
from .pets import router as pets_router
from .posts import router as posts_router
from .sighting_reports import router as sighting_reports_router
from .test import router as test_router
from .users import router as users_router

router = APIRouter(prefix="/v1")
router.include_router(gcs_signed_url_router)
router.include_router(health_router)
router.include_router(login_router)
router.include_router(logout_router)
router.include_router(missing_reports_router)
router.include_router(pets_router)
router.include_router(posts_router)
router.include_router(sighting_reports_router)
router.include_router(users_router)

router.include_router(test_router)
