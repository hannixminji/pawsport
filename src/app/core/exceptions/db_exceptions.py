from ..error_codes import ErrorCode
from . import AppException


class DatabaseError(AppException):
    status_code = 500

    def _default_code(self):
        return ErrorCode.DATABASE_ERROR


class TransientDatabaseError(DatabaseError):
    status_code = 503

    def _default_code(self):
        return ErrorCode.DATABASE_TRANSIENT_ERROR


class NonTransientDatabaseError(DatabaseError):
    status_code = 500

    def _default_code(self):
        return ErrorCode.DATABASE_ERROR
