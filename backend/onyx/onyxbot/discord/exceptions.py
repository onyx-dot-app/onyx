"""Custom exception classes for Discord bot."""


class DiscordBotError(Exception):
    """Base exception for Discord bot errors."""


class RegistrationError(DiscordBotError):
    """Error during guild registration."""


class SyncChannelsError(DiscordBotError):
    """Error during channel sync."""


class APIError(DiscordBotError):
    """Base API error."""


class CacheError(DiscordBotError):
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
