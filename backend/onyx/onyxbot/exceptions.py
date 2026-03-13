"""Shared exception classes for Onyx bot integrations (Discord, Teams, etc.)."""


class OnyxBotError(Exception):
    """Base exception for all Onyx bot errors."""


class RegistrationError(OnyxBotError):
    """Error during bot registration."""


class APIError(OnyxBotError):
    """Base API error."""


class CacheError(OnyxBotError):
    """Error during cache operations."""


class APIConnectionError(APIError):
    """Failed to connect to API."""


class APITimeoutError(APIError):
    """Request timed out."""


class APIResponseError(APIError):
    """API returned an error response."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code
