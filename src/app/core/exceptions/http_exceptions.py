# ruff: noqa
from fastapi import HTTPException, status

from ..error_codes import ErrorCode
from . import AppException


class CustomException(AppException):
    def __init__(self, status_code: int, detail: str, error_code: ErrorCode | None = None):
        self.status_code = status_code
        super().__init__(detail, error_code)

    def _default_code(self):
        if self.status_code >= 503:
            return ErrorCode.SERVICE_UNAVAILABLE
        return ErrorCode.INTERNAL_ERROR


class UnauthorizedException(AppException):
    status_code = 401

    def _default_code(self):
        return ErrorCode.USER_NOT_AUTHENTICATED


class RateLimitException(AppException):
    status_code = 429

    def _default_code(self):
        return ErrorCode.RATE_LIMIT_EXCEEDED


# --- kept as HTTPException for use in admin_sessions.py middleware only ---

class BadRequestException(HTTPException):
    def __init__(self, detail: str = "Bad request."):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class NotFoundException(HTTPException):
    def __init__(self, detail: str = "Not found."):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class DuplicateValueException(HTTPException):
    def __init__(self, detail: str = "Duplicate value."):
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


class UnprocessableEntityException(HTTPException):
    def __init__(self, detail: str = "Unprocessable entity."):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)
