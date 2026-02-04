from fastapi import APIRouter

from .article import router as article_router
from .gcs_signed_url import router as gcs_signed_url_router
from .health import router as health_router
from .missing_reports import router as missing_reports_router
from .notification_preferences import router as notification_preferences_router
from .pet_allergy import router as pet_allergy_router
from .pet_inventory import router as pet_inventory_router
from .pet_medical_condition import router as pet_medical_condition_router
from .pet_medication import router as pet_medication_router
from .pet_schedule import router as pet_schedule_router
from .pet_vaccination_record import router as pet_vaccination_record_router
from .pets import router as pets_router
from .push_tokens import router as push_tokens_router
from .sighting_reports import router as sighting_reports_router
from .test import router as test_router
from .test1 import router as test1_router
from .users import router as users_router

router = APIRouter(prefix="/v1")
router.include_router(article_router)
router.include_router(gcs_signed_url_router)
router.include_router(health_router)
router.include_router(missing_reports_router)
router.include_router(notification_preferences_router)
router.include_router(pet_allergy_router)
router.include_router(pet_inventory_router)
router.include_router(pet_medical_condition_router)
router.include_router(pet_medication_router)
router.include_router(pet_schedule_router)
router.include_router(pet_vaccination_record_router)
router.include_router(pets_router)
router.include_router(push_tokens_router)
router.include_router(sighting_reports_router)
router.include_router(users_router)

router.include_router(test_router)
router.include_router(test1_router)
