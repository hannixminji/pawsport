from enum import StrEnum


# -------------- system --------------
class ActorType(StrEnum):
    ADMIN_USER = "admin_user"
    MOBILE_USER = "mobile_user"


class AdminAccountStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class MobileUserAccountStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    BANNED = "banned"
    DEACTIVATED = "deactivated"


class ActionStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


# -------------- auth --------------
class AuthProvider(StrEnum):
    GOOGLE = "google.com"
    EMAIL = "email"
    ANONYMOUS = "anonymous"


# -------------- tokens --------------
class UserTokenType(StrEnum):
    EMAIL_VERIFICATION = "email_verification"
    EMAIL_CHANGE_OTP = "email_change_otp"
    EMAIL_CHANGE_AUTHORIZATION = "email_change_authorization"
    EMAIL_CHANGE = "email_change"
    PASSWORD_RESET = "password_reset"


# -------------- pet --------------
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


# -------------- medical --------------
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


# -------------- inventory --------------
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


# -------------- content --------------
class ArticleCategory(StrEnum):
    CARE = "care"
    HEALTH = "health"
    NUTRITION = "nutrition"
    TRAINING = "training"
    VET_VISIT = "vet_visit"


# -------------- reports --------------
class MissingReportStatus(StrEnum):
    LOST = "lost"
    FOUND = "found"
    RETURNED = "returned"
    CASE_CLOSED = "case_closed"


class MobileMissingReportStatus(StrEnum):
    LOST = "lost"
    FOUND = "found"
    RETURNED = "returned"
    CASE_CLOSED = "case_closed"


class SightingReportStatus(StrEnum):
    SIGHTED = "sighted"
    FOSTERED = "fostered"


# -------------- notifications --------------
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


# -------------- files --------------
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
