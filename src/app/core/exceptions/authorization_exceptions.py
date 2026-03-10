from ..error_codes import ErrorCode
from . import AppException


class ForbiddenError(AppException):
    status_code = 403

    def _default_code(self):
        return ErrorCode.FORBIDDEN


class ForbiddenException(AppException):
    status_code = 403

    def _default_code(self):
        return ErrorCode.FORBIDDEN


class PermissionDeniedError(AppException):
    status_code = 403

    def _default_code(self):
        return ErrorCode.FORBIDDEN
