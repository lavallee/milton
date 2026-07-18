"""Milton's public exception hierarchy."""


class MiltonError(Exception):
    """Base class for expected Milton failures."""


class ValidationError(MiltonError, ValueError):
    """A record violates a Milton data contract."""


class RecordConflictError(MiltonError):
    """A stable identifier was reused for different content."""


class LedgerCorruptionError(MiltonError):
    """An append-only ledger cannot be read safely."""
