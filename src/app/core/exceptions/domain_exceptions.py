class InvalidInputError(Exception):
    """Raised when an operation receives invalid input or violates validation rules."""


class NotFoundError(Exception):
    """Raised when a requested resource or entity is not found."""


class MLServiceError(Exception):
    """Raised when the ML service is unavailable or returns an unexpected response."""
