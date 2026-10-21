class SourceApiError(Exception):
    """An error response from a source's API, with what support needs to read
    it: the status, the request and the response body. A source gateway's API
    error subclasses it."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None,
        method: str | None = None,
        url: str | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.method = method
        self.url = url
        self.body = body


class ValidationError(Exception):
    """General exception for validation errors.

    A capability check can add the text its row shows: ``summary``, a short
    line of what is wrong or what stopped it, and ``description``, up to
    three lines of what happened and what is needed. ``message`` stays the
    full text, for logs and support.
    """

    def __init__(
        self,
        message: str,
        *,
        summary: str | None = None,
        description: str | None = None,
    ):
        self.message = message
        self.summary = summary
        self.description = description
        super().__init__(self.message)


class ConnectorValidationError(ValidationError):
    """General exception for connector validation errors."""


class UnexpectedValidationError(ValidationError):
    """Raised when an unexpected error occurs during connector validation.

    Unexpected errors don't necessarily mean the credential is invalid,
    but rather that there was an error during the validation process
    or we encountered a currently unhandled error case.

    Currently, unexpected validation errors are defined as transient and should not be
    used to disable the connector.
    """

    def __init__(
        self,
        message: str = "Unexpected error during connector validation",
        *,
        summary: str | None = None,
        description: str | None = None,
    ):
        super().__init__(message, summary=summary, description=description)


class RateLimitedValidationError(UnexpectedValidationError):
    """Raised when the source rate limits a validation. The credential may be
    fine: run the validation again later."""

    def __init__(
        self,
        message: str = "The source rate limited the validation",
        *,
        summary: str | None = None,
        description: str | None = None,
    ):
        super().__init__(message, summary=summary, description=description)


class UnreachableValidationError(UnexpectedValidationError):
    """Raised when Onyx cannot reach the source: the connection fails, or the
    address does not answer as the source's API."""

    def __init__(
        self,
        message: str = "Onyx cannot reach the source",
        *,
        summary: str | None = None,
        description: str | None = None,
    ):
        super().__init__(message, summary=summary, description=description)


class InconclusiveValidationError(UnexpectedValidationError):
    """Raised when a probe ran, but what it sampled cannot decide: the sample
    held nothing to test, or the source refused every try. Not proof of a
    broken credential, and not an unknown error."""


class NothingToCheckError(ValidationError):
    """Raised when a full read proves the scope has nothing for the check to
    test. The check is skipped: its row says what is missing."""


class CredentialInvalidError(ConnectorValidationError):
    """Raised when a connector's credential is invalid."""

    def __init__(
        self,
        message: str = "Credential is invalid",
        *,
        summary: str | None = None,
        description: str | None = None,
    ):
        super().__init__(message, summary=summary, description=description)


class CredentialExpiredError(ConnectorValidationError):
    """Raised when a connector's credential is expired."""

    def __init__(
        self,
        message: str = "Credential has expired",
        *,
        summary: str | None = None,
        description: str | None = None,
    ):
        super().__init__(message, summary=summary, description=description)


class InsufficientPermissionsError(ConnectorValidationError):
    """Raised when the credential does not have sufficient API permissions."""

    def __init__(
        self,
        message: str = "Insufficient permissions for the requested operation",
        *,
        summary: str | None = None,
        description: str | None = None,
    ):
        super().__init__(message, summary=summary, description=description)
