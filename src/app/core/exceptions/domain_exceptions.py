class InvalidInputError(Exception):
    """Raised when an operation receives invalid input or violates validation rules."""


class NotFoundError(Exception):
    """Raised when a requested resource or entity is not found."""


class DuplicateValueError(Exception):
    """Raised when an operation attempts to create or update a resource with a value that already exists."""


class UnauthorizedError(Exception):
    """Raised when an operation is attempted without valid authentication credentials."""


class BadRequestError(Exception):
    """Raised when a request is malformed or contains invalid parameters."""


class MLServiceError(Exception):
    """Raised when the ML service is unavailable or returns an unexpected response."""
