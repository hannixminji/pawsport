from fastapi import APIRouter

from .articles import router as article_router
from .auth import router as auth_router
from .dashboards import router as dashboard_router
from .missing_reports import router as missing_report_router
from .mobile_user_notification_preferences import router as mobile_user_notification_preference_router
from .mobile_users import router as mobile_user_router
from .permissions import router as permission_router
from .pet_allergies import router as pet_allergy_router
from .pet_inventories import router as pet_inventory_router
from .pet_medical_conditions import router as pet_medical_condition_router
from .pet_medications import router as pet_medication_router
from .pet_qr_defaults import router as pet_qr_default_router
from .pet_schedules import router as pet_schedule_router
from .pet_vaccination_records import router as pet_vaccination_record_router
from .pets import router as pet_router
from .rate_limits import router as rate_limit_router
from .roles import router as role_router
from .sighting_reports import router as sighting_report_router
from .tiers import router as tier_router
from .uploads import router as upload_router
from .users import router as user_router

router = APIRouter(prefix="/admin")

router.include_router(article_router)
router.include_router(auth_router)
router.include_router(dashboard_router)
router.include_router(missing_report_router)
router.include_router(mobile_user_notification_preference_router)
router.include_router(mobile_user_router)
router.include_router(permission_router)
router.include_router(pet_allergy_router)
router.include_router(pet_inventory_router)
router.include_router(pet_medical_condition_router)
router.include_router(pet_medication_router)
router.include_router(pet_qr_default_router)
router.include_router(pet_schedule_router)
router.include_router(pet_vaccination_record_router)
router.include_router(pet_router)
router.include_router(rate_limit_router)
router.include_router(role_router)
router.include_router(sighting_report_router)
router.include_router(tier_router)
router.include_router(upload_router)
router.include_router(user_router)
