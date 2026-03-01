class DatabaseError(Exception):
    """Base class for all database-related failures."""


class TransientDatabaseError(DatabaseError):
    """Retryable database failure (deadlock, timeout, connection drop)."""


class NonTransientDatabaseError(DatabaseError):
    """Non-retryable database failure (constraint violation, schema issue)."""
