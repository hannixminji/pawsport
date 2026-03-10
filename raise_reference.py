"""
raise_reference.py

This is a reference file — NOT meant to be run.
It shows the correct error_code to pass for every raise in the project.
Copy-paste the relevant raise into your service/router files.
"""

from .error_codes import ErrorCode
from .exceptions import (
    CustomException,
    DuplicateValueError,
    ForbiddenError,
    ForbiddenException,
    InvalidInputError,
    MLServiceError,
    NonTransientDatabaseError,
    NotFoundError,
    RateLimitException,
    TransientDatabaseError,
    UnauthorizedError,
    UnauthorizedException,
)

# =============================================================================
# AUTH / SESSION — UnauthorizedError / UnauthorizedException
# =============================================================================

raise UnauthorizedError("Invalid email or password.", error_code=ErrorCode.INVALID_CREDENTIALS)
raise UnauthorizedError("Invalid or expired refresh token.", error_code=ErrorCode.INVALID_OR_EXPIRED_REFRESH_TOKEN)
raise UnauthorizedError("Authentication failed due to conflicting account.", error_code=ErrorCode.AUTH_CONFLICTING_ACCOUNT)
raise UnauthorizedError("Failed to create session. Please try again later.", error_code=ErrorCode.SESSION_CREATE_FAILED)
raise UnauthorizedError("Failed to create session.", error_code=ErrorCode.SESSION_CREATE_FAILED)
raise UnauthorizedError("Failed to create guest session. Please try again.", error_code=ErrorCode.GUEST_SESSION_FAILED)
raise UnauthorizedError("Failed to create guest session. Please try again later.", error_code=ErrorCode.GUEST_SESSION_FAILED)
raise UnauthorizedError("Failed to create guest session.", error_code=ErrorCode.GUEST_SESSION_FAILED)
raise UnauthorizedError("User not found.", error_code=ErrorCode.USER_NOT_FOUND)
raise UnauthorizedError("Missing provider user ID in token.", error_code=ErrorCode.MISSING_PROVIDER_USER_ID)
raise UnauthorizedError("Missing provider user ID in token", error_code=ErrorCode.MISSING_PROVIDER_USER_ID)
raise UnauthorizedError("Email not provided in token.", error_code=ErrorCode.EMAIL_NOT_IN_TOKEN)
raise UnauthorizedError("Email not provided in token", error_code=ErrorCode.EMAIL_NOT_IN_TOKEN)

raise UnauthorizedException("User not authenticated.", error_code=ErrorCode.USER_NOT_AUTHENTICATED)
raise UnauthorizedException("Your session is no longer valid. Please log in again.", error_code=ErrorCode.SESSION_EXPIRED)
raise UnauthorizedException("Invalid token: missing provider user ID", error_code=ErrorCode.MISSING_PROVIDER_USER_ID)
raise UnauthorizedException("Invalid credentials", error_code=ErrorCode.INVALID_CREDENTIALS)
raise UnauthorizedException("Not authenticated", error_code=ErrorCode.USER_NOT_AUTHENTICATED)

# Account status (passed via dynamic message — update _check_account_status or equivalent)
# ErrorCode.ACCOUNT_SUSPENDED
# ErrorCode.ACCOUNT_BANNED
# ErrorCode.ACCOUNT_DEACTIVATED
# ErrorCode.ACCOUNT_INACTIVE
# ErrorCode.GUEST_SESSION_SUSPENDED
# ErrorCode.GUEST_SESSION_BANNED
# ErrorCode.GUEST_SESSION_INACTIVE


# =============================================================================
# FORBIDDEN — ForbiddenError / ForbiddenException
# =============================================================================

# Generic forbidden — no specific code needed, Flutter shows generic "no permission" message
raise ForbiddenError("You do not have permission to perform this action.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to create a pet.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to search pets.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view pets.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view this pet.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to update this pet.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to delete this pet.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to access this pet.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to create a missing report.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view missing reports.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view this missing report.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to update this missing report.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to update this missing report's status.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to delete this missing report.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to create a sighting report.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view sighting reports.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view this sighting report.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to update this sighting report.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to delete this sighting report.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to access this sighting report.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to create an inventory item.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to search inventory.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view inventory items.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view this inventory item.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to update this inventory item.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to access this inventory item.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to access this pet allergy.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to search pet allergies.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view pet allergies.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view this pet allergy.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to update this pet allergy.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to access this pet medical condition.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to search pet medical conditions.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view pet medical conditions.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view this pet medical condition.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to update this pet medical condition.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to access this pet medication.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to search pet medications.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view pet medications.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view this pet medication.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to update this pet medication.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to access this pet schedule.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to search pet schedules.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view pet schedules.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view this pet schedule.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to update this pet schedule.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to access this vaccination record.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to search vaccination records.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view vaccination records.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view this vaccination record.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to update this vaccination record.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view this user.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to update this user.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to search mobile users.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to change this user's password.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to upsert push tokens.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to delete push tokens.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view notification preferences.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to upsert notification preferences.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to view QR default preferences.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to upsert QR default preferences.", error_code=ErrorCode.FORBIDDEN)

# Admin required
raise ForbiddenError("Admin privileges are required to create a mobile user.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to create an article.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to update an article.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to delete an article.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to delete articles.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to permanently delete an article.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to permanently delete articles.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to perform this action.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to perform this search.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to create a rate limit.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to search rate limits.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to view rate limits.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to view this rate limit.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to update a rate limit.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to delete a rate limit.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to delete rate limits in bulk.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to permanently delete a rate limit.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to permanently delete rate limits.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to create a tier.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to update a tier.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to update user tiers.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to update a user's tier.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to update a user's account status.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to delete a user.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to delete inventory items in bulk.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to delete pet allergies.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to delete pet medical conditions.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to delete pet medications.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to delete pet schedules.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)
raise ForbiddenError("Admin privileges are required to delete vaccination records in bulk.", error_code=ErrorCode.FORBIDDEN_ADMIN_REQUIRED)

# Superuser required
raise ForbiddenError("Superuser privileges are required to permanently delete a pet.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete a user.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete a missing report.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete a sighting report.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete an inventory item.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete inventory items.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete the pet allergy.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete pet allergies.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete the pet medical condition.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete pet medical conditions.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete the pet medication.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete pet medications.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete the pet schedule.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete pet schedules.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete the vaccination record.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete vaccination records.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete a tier.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete tiers.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to create an admin permission.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to perform this search.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to perform this action.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to update an admin permission.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete an admin permission.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete admin permissions.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to create an admin role.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to update an admin role.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete an admin role.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete admin roles.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to assign permissions to a role.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to remove permissions from a role.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to create an admin user.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to view admin user roles.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to delete an admin user.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to delete admin users.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete an admin user.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to permanently delete admin users.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to update an admin user's account status.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to assign roles to an admin user.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to remove roles from an admin user.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to assign direct permissions to an admin user.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to remove direct permissions from an admin user.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to search action logs.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to view action logs.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("Superuser privileges are required to view an action log entry.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenError("You do not have permission to view this admin user.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenError("You do not have permission to change this user's password.", error_code=ErrorCode.FORBIDDEN)

raise ForbiddenException("You do not have any roles assigned.", error_code=ErrorCode.FORBIDDEN_NO_ROLES_ASSIGNED)
raise ForbiddenException("You do not have permission to perform this action.", error_code=ErrorCode.FORBIDDEN)
raise ForbiddenException("You do not have permission to perform this action. Superuser access is required.", error_code=ErrorCode.FORBIDDEN_SUPERUSER_REQUIRED)
raise ForbiddenException("Your account has been suspended. Please contact support for assistance.", error_code=ErrorCode.ACCOUNT_SUSPENDED)
raise ForbiddenException("Your account is inactive. Please contact an administrator to reactivate it.", error_code=ErrorCode.ACCOUNT_INACTIVE)
raise ForbiddenException("Your account has been suspended. Please contact support.", error_code=ErrorCode.ACCOUNT_SUSPENDED)
raise ForbiddenException("Your account is inactive.", error_code=ErrorCode.ACCOUNT_INACTIVE)
raise ForbiddenException("Your account is not active.", error_code=ErrorCode.ACCOUNT_INACTIVE)


# =============================================================================
# RATE LIMIT — RateLimitException
# =============================================================================

raise RateLimitException("Rate limit exceeded.", error_code=ErrorCode.RATE_LIMIT_EXCEEDED)
raise RateLimitException("Too many login attempts. Please try again later.", error_code=ErrorCode.TOO_MANY_LOGIN_ATTEMPTS)


# =============================================================================
# NOT FOUND — NotFoundError
# =============================================================================

raise NotFoundError("User not found.", error_code=ErrorCode.USER_NOT_FOUND)
raise NotFoundError("Pet not found.", error_code=ErrorCode.PET_NOT_FOUND)
raise NotFoundError("Missing report not found.", error_code=ErrorCode.MISSING_REPORT_NOT_FOUND)
raise NotFoundError("Sighting report not found.", error_code=ErrorCode.SIGHTING_REPORT_NOT_FOUND)
raise NotFoundError("Inventory item not found.", error_code=ErrorCode.INVENTORY_ITEM_NOT_FOUND)
raise NotFoundError("Pet allergy not found.", error_code=ErrorCode.PET_ALLERGY_NOT_FOUND)
raise NotFoundError("Pet medical condition not found.", error_code=ErrorCode.PET_MEDICAL_CONDITION_NOT_FOUND)
raise NotFoundError("Pet medication not found.", error_code=ErrorCode.PET_MEDICATION_NOT_FOUND)
raise NotFoundError("Pet schedule not found.", error_code=ErrorCode.PET_SCHEDULE_NOT_FOUND)
raise NotFoundError("Vaccination record not found.", error_code=ErrorCode.VACCINATION_RECORD_NOT_FOUND)
raise NotFoundError("Article not found.", error_code=ErrorCode.ARTICLE_NOT_FOUND)
raise NotFoundError("Tier not found.", error_code=ErrorCode.TIER_NOT_FOUND)
raise NotFoundError("Rate limit not found.", error_code=ErrorCode.RATE_LIMIT_NOT_FOUND)
raise NotFoundError("Push token not found.", error_code=ErrorCode.PUSH_TOKEN_NOT_FOUND)
raise NotFoundError("QR preference not found.", error_code=ErrorCode.QR_PREFERENCE_NOT_FOUND)
raise NotFoundError("Admin user not found.", error_code=ErrorCode.ADMIN_USER_NOT_FOUND)
raise NotFoundError("Admin role not found.", error_code=ErrorCode.ADMIN_ROLE_NOT_FOUND)
raise NotFoundError("Admin permission not found.", error_code=ErrorCode.ADMIN_PERMISSION_NOT_FOUND)
raise NotFoundError("Action log entry not found.", error_code=ErrorCode.ACTION_LOG_NOT_FOUND)
raise NotFoundError("This login method is not linked to your account.", error_code=ErrorCode.LOGIN_METHOD_NOT_FOUND)
raise NotFoundError("No email/password linked account found for this user.", error_code=ErrorCode.EMAIL_PASSWORD_ACCOUNT_NOT_FOUND)
raise NotFoundError("One or more images you're trying to keep were not found.", error_code=ErrorCode.IMAGES_TO_KEEP_NOT_FOUND)
raise NotFoundError("One or more attachments you're trying to keep were not found.", error_code=ErrorCode.ATTACHMENTS_TO_KEEP_NOT_FOUND)
raise NotFoundError("Some profile images you're trying to keep were not found.", error_code=ErrorCode.PROFILE_IMAGES_TO_KEEP_NOT_FOUND)


# =============================================================================
# DUPLICATE — DuplicateValueError
# =============================================================================

raise DuplicateValueError("A user with this email already exists.", error_code=ErrorCode.EMAIL_ALREADY_EXISTS)
raise DuplicateValueError("Username conflict. Please try again.", error_code=ErrorCode.USERNAME_CONFLICT)
raise DuplicateValueError("Unable to complete registration. Please try again.", error_code=ErrorCode.REGISTRATION_FAILED)
raise DuplicateValueError("This email is already connected to an account.", error_code=ErrorCode.EMAIL_ALREADY_CONNECTED)
raise DuplicateValueError("Unable to complete signup. Please try again.", error_code=ErrorCode.REGISTRATION_FAILED)


# =============================================================================
# INVALID INPUT — User / Auth
# =============================================================================

raise InvalidInputError("Email is already verified.", error_code=ErrorCode.EMAIL_ALREADY_VERIFIED)
raise InvalidInputError("No email address found for this user.", error_code=ErrorCode.NO_EMAIL_ON_ACCOUNT)
raise InvalidInputError("New email must be different from your current email.", error_code=ErrorCode.NEW_EMAIL_SAME_AS_CURRENT)
raise InvalidInputError("Password is required to change your email.", error_code=ErrorCode.PASSWORD_REQUIRED_FOR_EMAIL_CHANGE)
raise InvalidInputError("Current password is incorrect.", error_code=ErrorCode.INCORRECT_CURRENT_PASSWORD)
raise InvalidInputError("The profile image may not have been uploaded correctly.", error_code=ErrorCode.PROFILE_IMAGE_UPLOAD_FAILED)
raise InvalidInputError("Invalid or expired token.", error_code=ErrorCode.TOKEN_INVALID_OR_EXPIRED)
raise InvalidInputError("A user with this email already exists.", error_code=ErrorCode.EMAIL_ALREADY_EXISTS)
raise InvalidInputError("A user with this username already exists.", error_code=ErrorCode.USERNAME_CONFLICT)
raise InvalidInputError("A user with this phone number already exists.", error_code=ErrorCode.PHONE_NUMBER_ALREADY_EXISTS)
raise InvalidInputError("Unable to create the mobile user.", error_code=ErrorCode.INTERNAL_ERROR)
raise InvalidInputError("Unable to update the user.", error_code=ErrorCode.INTERNAL_ERROR)
raise InvalidInputError("Unable to delete the user because it is referenced by other records.", error_code=ErrorCode.USER_REFERENCED_BY_OTHER_RECORDS)

# Linked accounts
raise InvalidInputError("An email and password login method is already linked to this account.", error_code=ErrorCode.EMAIL_PASSWORD_ALREADY_LINKED)
raise InvalidInputError("This email is already linked to another account.", error_code=ErrorCode.EMAIL_ALREADY_LINKED_TO_ANOTHER)
raise InvalidInputError("A Google login method is already linked to this account.", error_code=ErrorCode.GOOGLE_ALREADY_LINKED)
raise InvalidInputError("This Google account is already linked to another account.", error_code=ErrorCode.GOOGLE_LINKED_TO_ANOTHER)
raise InvalidInputError("You must have at least one login method linked to your account.", error_code=ErrorCode.LAST_LOGIN_METHOD)
raise InvalidInputError("Your password is required to confirm changes to linked login methods.", error_code=ErrorCode.PASSWORD_REQUIRED_FOR_PROVIDER_CHANGE)
raise InvalidInputError("Unable to add email and password login method. Please try again.", error_code=ErrorCode.ADD_EMAIL_PASSWORD_FAILED)
raise InvalidInputError("Unable to add Google login method. Please try again.", error_code=ErrorCode.ADD_GOOGLE_FAILED)


# =============================================================================
# INVALID INPUT — Missing Reports
# =============================================================================

raise InvalidInputError("Missing reports are only supported for dogs and cats.", error_code=ErrorCode.MISSING_REPORT_UNSUPPORTED_SPECIES)
raise InvalidInputError("A missing report for this pet already exists.", error_code=ErrorCode.MISSING_REPORT_ALREADY_EXISTS)
raise InvalidInputError("Missing report status is already final and cannot be changed.", error_code=ErrorCode.MISSING_REPORT_STATUS_FINAL)
raise InvalidInputError("Cannot revert a final missing report back to lost.", error_code=ErrorCode.MISSING_REPORT_CANNOT_REVERT_TO_LOST)
raise InvalidInputError("Unable to create the missing report.", error_code=ErrorCode.MISSING_REPORT_CREATE_FAILED)
raise InvalidInputError("Unable to update the missing report.", error_code=ErrorCode.MISSING_REPORT_UPDATE_FAILED)


# =============================================================================
# INVALID INPUT — Pets
# =============================================================================

raise InvalidInputError("Invalid pet species. Must be 'cat' or 'dog'.", error_code=ErrorCode.INVALID_PET_SPECIES)
raise InvalidInputError("Invalid species. Must be 'cat' or 'dog'.", error_code=ErrorCode.INVALID_PET_SPECIES)
raise InvalidInputError("Some image files might not have been uploaded. Please upload them and try again.", error_code=ErrorCode.PET_IMAGE_UPLOAD_FAILED)
raise InvalidInputError("Please upload a valid image file — only JPG and PNG formats are supported.", error_code=ErrorCode.PET_IMAGE_INVALID_FORMAT)
raise InvalidInputError("Unable to create the pet. Please try again later.", error_code=ErrorCode.PET_CREATE_FAILED)
# Dynamic: raise InvalidInputError(ml_response.get("message", "Failed to detect a valid pet in the image."), error_code=ErrorCode.PET_IMAGE_NO_PET_DETECTED)
# Dynamic: raise InvalidInputError(f"{base} (Problem photos: {bad_label})" ..., error_code=ErrorCode.PET_IMAGE_UPLOAD_FAILED)


# =============================================================================
# INVALID INPUT — Pet Health Records
# =============================================================================

raise InvalidInputError("This allergen already exists for this pet.", error_code=ErrorCode.PET_ALLERGY_ALREADY_EXISTS)
raise InvalidInputError("Unable to create the pet allergy.", error_code=ErrorCode.PET_ALLERGY_CREATE_FAILED)
raise InvalidInputError("Unable to update the pet allergy.", error_code=ErrorCode.PET_ALLERGY_UPDATE_FAILED)
raise InvalidInputError("This medical condition already exists for this pet.", error_code=ErrorCode.PET_MEDICAL_CONDITION_ALREADY_EXISTS)
raise InvalidInputError("Unable to create the pet medical condition.", error_code=ErrorCode.PET_MEDICAL_CONDITION_CREATE_FAILED)
raise InvalidInputError("Unable to update the pet medical condition.", error_code=ErrorCode.PET_MEDICAL_CONDITION_UPDATE_FAILED)
raise InvalidInputError("This medication already exists for this pet.", error_code=ErrorCode.PET_MEDICATION_ALREADY_EXISTS)
raise InvalidInputError("Unable to create the pet medication.", error_code=ErrorCode.PET_MEDICATION_CREATE_FAILED)
raise InvalidInputError("Unable to update the pet medication.", error_code=ErrorCode.PET_MEDICATION_UPDATE_FAILED)
raise InvalidInputError("Unable to create the pet schedule.", error_code=ErrorCode.PET_SCHEDULE_CREATE_FAILED)  # if needed
raise InvalidInputError("Unable to update the pet schedule.", error_code=ErrorCode.PET_SCHEDULE_UPDATE_FAILED)  # if needed


# =============================================================================
# INVALID INPUT — Vaccination Records
# =============================================================================

raise InvalidInputError("Some attachment files might not have been uploaded. Please upload them and try again.", error_code=ErrorCode.VACCINATION_ATTACHMENT_UPLOAD_FAILED)
raise InvalidInputError("Attachment metadata missing mime_type. Please re-upload the file.", error_code=ErrorCode.VACCINATION_ATTACHMENT_MISSING_MIME)
raise InvalidInputError("Attachment metadata has invalid mime_type. Please re-upload the file.", error_code=ErrorCode.VACCINATION_ATTACHMENT_INVALID_MIME)
raise InvalidInputError("Please arrange the attachments in a valid order.", error_code=ErrorCode.VACCINATION_ATTACHMENT_INVALID_ORDER)
raise InvalidInputError("Unable to create the vaccination record.", error_code=ErrorCode.VACCINATION_RECORD_CREATE_FAILED)
raise InvalidInputError("Unable to update the vaccination record.", error_code=ErrorCode.VACCINATION_RECORD_UPDATE_FAILED)
# Dynamic: raise InvalidInputError(f"You can only have up to {MAX} attachments per vaccination record.", error_code=ErrorCode.VACCINATION_ATTACHMENT_LIMIT_EXCEEDED)
# Dynamic: raise InvalidInputError(f"Total size of uploaded attachments exceeds the {limit_mb}MB limit.", error_code=ErrorCode.VACCINATION_ATTACHMENT_SIZE_EXCEEDED)


# =============================================================================
# INVALID INPUT — Inventory
# =============================================================================

raise InvalidInputError("Some image files might not have been uploaded. Please upload them and try again.", error_code=ErrorCode.INVENTORY_IMAGE_UPLOAD_FAILED)
raise InvalidInputError("Image metadata missing mime_type. Please re-upload the file.", error_code=ErrorCode.INVENTORY_IMAGE_MISSING_MIME)
raise InvalidInputError("Image metadata has invalid mime_type. Please re-upload the file.", error_code=ErrorCode.INVENTORY_IMAGE_INVALID_MIME)
raise InvalidInputError("Please arrange the images in a valid order.", error_code=ErrorCode.INVENTORY_IMAGE_INVALID_ORDER)
raise InvalidInputError("An item with this name already exists.", error_code=ErrorCode.INVENTORY_NAME_ALREADY_EXISTS)
raise InvalidInputError("Unable to create the inventory item.", error_code=ErrorCode.INVENTORY_CREATE_FAILED)
raise InvalidInputError("Unable to update the inventory item.", error_code=ErrorCode.INVENTORY_UPDATE_FAILED)
# Dynamic: raise InvalidInputError(f"You can only have up to {MAX} images per inventory item.", error_code=ErrorCode.INVENTORY_IMAGE_LIMIT_EXCEEDED)
# Dynamic: raise InvalidInputError(f"Total size of uploaded images exceeds the {limit_mb}MB limit.", error_code=ErrorCode.INVENTORY_IMAGE_SIZE_EXCEEDED)


# =============================================================================
# INVALID INPUT — Sighting Reports
# =============================================================================

raise InvalidInputError("Some image files might not have been uploaded. Please upload them and try again.", error_code=ErrorCode.SIGHTING_IMAGE_UPLOAD_FAILED)
raise InvalidInputError("Image metadata has invalid mime_type. Please re-upload the file.", error_code=ErrorCode.SIGHTING_IMAGE_INVALID_MIME)
raise InvalidInputError("Please arrange the images in a valid order.", error_code=ErrorCode.SIGHTING_IMAGE_INVALID_ORDER)
raise InvalidInputError("Unable to create the sighting report.", error_code=ErrorCode.SIGHTING_REPORT_CREATE_FAILED)
raise InvalidInputError("Unable to update the sighting report.", error_code=ErrorCode.SIGHTING_REPORT_UPDATE_FAILED)
# Dynamic: raise InvalidInputError(f"You can only have up to {MAX} images per sighting report.", error_code=ErrorCode.SIGHTING_IMAGE_LIMIT_EXCEEDED)
# Dynamic: raise InvalidInputError(f"Total size of uploaded images exceeds the {limit_mb}MB limit.", error_code=ErrorCode.SIGHTING_IMAGE_SIZE_EXCEEDED)


# =============================================================================
# INVALID INPUT — Upload Service
# =============================================================================

raise InvalidInputError("At least one filename must be provided.", error_code=ErrorCode.UPLOAD_NO_FILES_PROVIDED)
# Dynamic: raise InvalidInputError(f"Filename '{filename}' must have a valid extension", error_code=ErrorCode.UPLOAD_INVALID_EXTENSION)
# Dynamic: raise InvalidInputError(f"Filename '{filename}' must be one of: {supported}", error_code=ErrorCode.UPLOAD_INVALID_FILE_TYPE)
# Dynamic: raise InvalidInputError(f"Cannot upload more than {MAX} files at once.", error_code=ErrorCode.UPLOAD_TOO_MANY_FILES)


# =============================================================================
# INVALID INPUT — Search Engine
# =============================================================================

# Dynamic: raise InvalidInputError(f"Unknown or disallowed field: '{name}'.", error_code=ErrorCode.SEARCH_UNKNOWN_FIELD)
# Dynamic: raise InvalidInputError(f"Filter nesting exceeds the maximum allowed depth of {max}.", error_code=ErrorCode.SEARCH_FILTER_TOO_DEEP)
raise InvalidInputError("A filter group must contain at least one condition.", error_code=ErrorCode.SEARCH_EMPTY_FILTER_GROUP)
# Dynamic: raise InvalidInputError(f"Operator '{op}' is not allowed on field '{field}'.", error_code=ErrorCode.SEARCH_OPERATOR_NOT_ALLOWED)
# Dynamic: raise InvalidInputError(f"Sorting by '{sort_by}' is not permitted.", error_code=ErrorCode.SEARCH_INVALID_SORT_FIELD)
raise InvalidInputError("Both 'page' and 'items_per_page' must be positive integers.", error_code=ErrorCode.SEARCH_INVALID_PAGINATION)
raise InvalidInputError("ILIKE requires a string value.", error_code=ErrorCode.SEARCH_INVALID_FILTER_VALUE)
raise InvalidInputError("IN / NOT_IN requires a list value.", error_code=ErrorCode.SEARCH_INVALID_FILTER_VALUE)
raise InvalidInputError("IN / NOT_IN requires a non-empty list.", error_code=ErrorCode.SEARCH_INVALID_FILTER_VALUE)
# Dynamic: raise InvalidInputError(f"IN / NOT_IN list length exceeds maximum.", error_code=ErrorCode.SEARCH_INVALID_FILTER_VALUE)
# Dynamic: raise InvalidInputError(f"'{value}' is not a valid {enum}.", error_code=ErrorCode.SEARCH_INVALID_FILTER_VALUE)


# =============================================================================
# INVALID INPUT — Admin
# =============================================================================

raise InvalidInputError("A permission with this key already exists.", error_code=ErrorCode.ADMIN_PERMISSION_KEY_ALREADY_EXISTS)
raise InvalidInputError("Unable to create the admin permission.", error_code=ErrorCode.ADMIN_PERMISSION_CREATE_FAILED)
raise InvalidInputError("Unable to update the admin permission.", error_code=ErrorCode.ADMIN_PERMISSION_UPDATE_FAILED)
raise InvalidInputError("A role with this name already exists.", error_code=ErrorCode.ADMIN_ROLE_NAME_ALREADY_EXISTS)
raise InvalidInputError("Unable to create the admin role.", error_code=ErrorCode.ADMIN_ROLE_CREATE_FAILED)
raise InvalidInputError("Unable to update the admin role.", error_code=ErrorCode.ADMIN_ROLE_UPDATE_FAILED)
# Dynamic: raise InvalidInputError(f"Permission IDs not found: {ids}", error_code=ErrorCode.ADMIN_ROLE_PERMISSION_IDS_NOT_FOUND)
raise InvalidInputError("Unable to create the admin user.", error_code=ErrorCode.ADMIN_USER_CREATE_FAILED)
raise InvalidInputError("Unable to update the admin user.", error_code=ErrorCode.ADMIN_USER_UPDATE_FAILED)
# Dynamic: raise InvalidInputError(f"Role IDs not found: {ids}", error_code=ErrorCode.ADMIN_USER_ROLE_IDS_NOT_FOUND)
# Dynamic: raise InvalidInputError(f"Permission IDs not found: {ids}", error_code=ErrorCode.ADMIN_USER_PERMISSION_IDS_NOT_FOUND)
raise InvalidInputError("An article with this title already exists.", error_code=ErrorCode.ARTICLE_TITLE_ALREADY_EXISTS)
raise InvalidInputError("Unable to create the article.", error_code=ErrorCode.ARTICLE_CREATE_FAILED)
raise InvalidInputError("Unable to update the article.", error_code=ErrorCode.ARTICLE_UPDATE_FAILED)
raise InvalidInputError("A tier with this name already exists.", error_code=ErrorCode.TIER_NAME_ALREADY_EXISTS)
raise InvalidInputError("Unable to create the tier.", error_code=ErrorCode.TIER_CREATE_FAILED)
raise InvalidInputError("Unable to update the tier.", error_code=ErrorCode.TIER_UPDATE_FAILED)
raise InvalidInputError("A rate limit with this name already exists for this tier.", error_code=ErrorCode.RATE_LIMIT_NAME_ALREADY_EXISTS)
raise InvalidInputError("A rate limit for this path already exists for this tier.", error_code=ErrorCode.RATE_LIMIT_PATH_ALREADY_EXISTS)
raise InvalidInputError("Unable to create the rate limit.", error_code=ErrorCode.RATE_LIMIT_CREATE_FAILED)
raise InvalidInputError("Unable to update the rate limit.", error_code=ErrorCode.RATE_LIMIT_UPDATE_FAILED)


# =============================================================================
# ML SERVICE — MLServiceError
# =============================================================================

raise MLServiceError("Please try again in a bit.", error_code=ErrorCode.ML_GENERIC_ERROR)
raise MLServiceError("Something went wrong. Please try again.", error_code=ErrorCode.ML_GENERIC_ERROR)
raise MLServiceError("The ML service took too long to respond. Please try again.", error_code=ErrorCode.ML_SERVICE_TIMEOUT)
raise MLServiceError("Unable to connect to the ML service. Please try again later.", error_code=ErrorCode.ML_SERVICE_UNAVAILABLE)
raise MLServiceError("The ML service returned an unexpected response.", error_code=ErrorCode.ML_SERVICE_UNEXPECTED_RESPONSE)
raise MLServiceError("Something went wrong while processing the image.", error_code=ErrorCode.ML_IMAGE_PROCESSING_FAILED)
# Dynamic: raise MLServiceError(f"Vector search failed: {error}", error_code=ErrorCode.ML_VECTOR_SEARCH_FAILED)


# =============================================================================
# SERVER / DATABASE — TransientDatabaseError / NonTransientDatabaseError
# =============================================================================
# These all use their class default (DATABASE_TRANSIENT_ERROR / DATABASE_ERROR).
# No need to pass error_code explicitly — Flutter shows generic "try again" for all of them.
# Example:
raise TransientDatabaseError("Failed to create the pet. Please try again later.")
raise NonTransientDatabaseError("Failed to create the pet.")


# =============================================================================
# CUSTOM EXCEPTION
# =============================================================================

raise CustomException(status_code=503, detail="Admin session store is not available", error_code=ErrorCode.SERVICE_UNAVAILABLE)
raise CustomException(status_code=503, detail="Unable to verify permissions at this time.", error_code=ErrorCode.SERVICE_UNAVAILABLE)
raise CustomException(status_code=503, detail="Permission verification failed due to an internal error.", error_code=ErrorCode.SERVICE_UNAVAILABLE)
raise CustomException(status_code=500, detail="An unexpected error occurred. Please try again later.", error_code=ErrorCode.INTERNAL_ERROR)
raise CustomException(status_code=500, detail="An unexpected error occurred.", error_code=ErrorCode.INTERNAL_ERROR)
