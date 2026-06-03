"""Exception types raised by the build session layer.

Kept in a tiny module so callers can import them without pulling in the
full SessionManager dependency tree.
"""


class RateLimitError(Exception):
    """Raised by ``SessionManager.check_rate_limit`` when the user has
    exhausted their build-mode message budget."""

    def __init__(
        self,
        message: str,
        messages_used: int,
        limit: int,
        reset_timestamp: str | None = None,
    ) -> None:
        super().__init__(message)
        self.messages_used = messages_used
        self.limit = limit
        self.reset_timestamp = reset_timestamp


class UploadLimitExceededError(ValueError):
    """Raised when an upload would exceed the per-session file count or
    total size limit."""


class SandboxProvisioningError(RuntimeError):
    """Raised when a sandbox is mid-provision and the caller cannot wait
    it out."""
