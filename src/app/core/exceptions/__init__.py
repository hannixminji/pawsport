from ..error_codes import ErrorCode


class AppException(Exception):
    status_code: int = 500

    def __init__(self, message: str, error_code: ErrorCode | None = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self._default_code()

    def _default_code(self) -> ErrorCode:
        return ErrorCode.INTERNAL_ERROR
