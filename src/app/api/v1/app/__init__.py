from fastapi import APIRouter

from .articles import router as article_router
from .auth import router as auth_router
from .device_push_tokens import router as device_push_token_router
from .missing_reports import router as missing_report_router
from .notification_preferences import router as notification_preference_router
from .pet_allergies import router as pet_allergy_router
from .pet_inventories import router as pet_inventory_router
from .pet_medical_conditions import router as pet_medical_condition_router
from .pet_medications import router as pet_medication_router
from .pet_qr_defaults import router as pet_qr_default_router
from .pet_schedules import router as pet_schedule_router
from .pet_vaccination_records import router as pet_vaccination_record_router
from .pets import router as pet_router
from .sighting_reports import router as sighting_report_router
from .uploads import router as upload_router
from .users import router as user_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(article_router)
router.include_router(device_push_token_router)
router.include_router(missing_report_router)
router.include_router(notification_preference_router)
router.include_router(user_router)
router.include_router(pet_allergy_router)
router.include_router(pet_inventory_router)
router.include_router(pet_medical_condition_router)
router.include_router(pet_medication_router)
router.include_router(pet_qr_default_router)
router.include_router(pet_schedule_router)
router.include_router(pet_vaccination_record_router)
router.include_router(pet_router)
router.include_router(sighting_report_router)
router.include_router(upload_router)
