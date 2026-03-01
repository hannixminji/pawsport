class ForbiddenError(Exception):
    """Raised when an action requires superuser privileges."""


class PermissionDeniedError(Exception):
    """Raised when an actor lacks the required permission to perform an action."""
