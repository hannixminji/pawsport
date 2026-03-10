from ..error_codes import ErrorCode
from . import AppException


class InvalidInputError(AppException):
    status_code = 422

    def _default_code(self):
        return ErrorCode.INVALID_INPUT


class NotFoundError(AppException):
    status_code = 404

    def _default_code(self):
        return ErrorCode.INTERNAL_ERROR


class DuplicateValueError(AppException):
    status_code = 409

    def _default_code(self):
        return ErrorCode.INTERNAL_ERROR


class UnauthorizedError(AppException):
    status_code = 401

    def _default_code(self):
        return ErrorCode.USER_NOT_AUTHENTICATED


class MLServiceError(AppException):
    status_code = 503

    def _default_code(self):
        return ErrorCode.ML_GENERIC_ERROR
