from enum import StrEnum


class ActorType(StrEnum):
    ADMIN_USER = "admin_user"
    MOBILE_USER = "mobile_user"


class AdminAccountStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class AuthProvider(StrEnum):
    GOOGLE = "google"


class PetSpecies(StrEnum):
    DOG = "dog"
    CAT = "cat"


class PetSex(StrEnum):
    MALE = "male"
    FEMALE = "female"


class PetScheduleType(StrEnum):
    VET_VISIT = "vet_visit"
    VACCINATION = "vaccination"
    GROOMING = "grooming"
    FOOD = "food"
    WALK = "walk"
    MEDICINE = "medicine"
    PLAY_TIME = "play_time"
    OTHER = "other"


class VaccineType(StrEnum):
    CORE = "core"
    NON_CORE = "non_core"


class AllergenType(StrEnum):
    FOOD = "food"
    MEDICATION = "medication"
    ENVIRONMENTAL = "environmental"
    OTHER = "other"


class AllergySeverity(StrEnum):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


class MedicalConditionSeverity(StrEnum):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


class MedicalConditionStatus(StrEnum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    CHRONIC = "chronic"


class MedicationFrequency(StrEnum):
    ONCE_DAILY = "once_daily"
    TWICE_DAILY = "twice_daily"
    THREE_TIMES_DAILY = "three_times_daily"
    EVERY_OTHER_DAY = "every_other_day"
    WEEKLY = "weekly"
    AS_NEEDED = "as_needed"


class MedicationAdministrationRoute(StrEnum):
    ORAL = "oral"
    TOPICAL = "topical"
    INJECTION = "injection"
    INHALATION = "inhalation"
    OCULAR = "ocular"
    OTIC = "otic"
    OTHER = "other"


class MedicationStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    DISCONTINUED = "discontinued"
    PAUSED = "paused"
    SCHEDULED = "scheduled"


class InventoryType(StrEnum):
    FOOD = "food"
    MEDICINE = "medicine"


class InventoryUnit(StrEnum):
    KG = "kg"
    G = "g"
    LB = "lb"
    PCS = "pcs"
    BOTTLES = "bottles"
    TABLETS = "tablets"
    ML = "ml"


class ArticleCategory(StrEnum):
    CARE = "care"
    HEALTH = "health"
    NUTRITION = "nutrition"
    TRAINING = "training"
    VET_VISIT = "vet_visit"


class MissingReportStatus(StrEnum):
    LOST = "lost"
    FOUND = "found"
    RETURNED = "returned"
    FOSTERED = "fostered"
    CASE_CLOSED = "case_closed"


class NotificationFeature(StrEnum):
    NEARBY_REPORT_ALERTS = "nearby_report_alerts"
    PET_SCHEDULE_REMINDERS = "pet_schedule_reminders"


class PushTokenPlatform(StrEnum):
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"


class PushTokenProvider(StrEnum):
    FCM = "fcm"
    APNS = "apns"
    WEBPUSH = "webpush"


class MimeType(StrEnum):
    JPEG = "image/jpeg"
    PNG = "image/png"


class AttachmentMimeType(StrEnum):
    PDF = "application/pdf"
    JPEG = "image/jpeg"
    PNG = "image/png"


class FileExtension(StrEnum):
    JPG = "jpg"
    JPEG = "jpeg"
    PNG = "png"
    PDF = "pdf"
