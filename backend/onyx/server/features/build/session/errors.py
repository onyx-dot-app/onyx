"""Exception types raised by the build session layer.

Kept in a tiny module so callers can import them without pulling in the
full SessionManager dependency tree.
"""


class UploadLimitExceededError(ValueError):
    """Raised when an upload would exceed the per-session file count or
    total size limit."""


class SandboxProvisioningError(RuntimeError):
    """Raised when a sandbox is mid-provision and the caller cannot wait
    it out."""


class SandboxProvisioningInProgressError(SandboxProvisioningError):
    """A live provisioning attempt (recent committed ``PROVISIONING``
    attempt) already owns the sandbox; the caller should retry shortly."""


class StaleProvisioningAttemptError(SandboxProvisioningError):
    """This attempt was superseded before it could finalize;
    its external work must not be recorded as the current runtime."""
