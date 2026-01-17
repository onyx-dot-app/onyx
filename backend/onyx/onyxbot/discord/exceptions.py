"""Custom exception classes for Discord bot."""


class DiscordBotError(Exception):
    """Base exception for Discord bot errors."""


class ConfigurationError(DiscordBotError):
    """Error in bot configuration."""


class RegistrationError(DiscordBotError):
    """Error during guild registration."""


class InvalidRegistrationKeyError(RegistrationError):
    """Registration key is invalid or malformed."""


class RegistrationKeyAlreadyUsedError(RegistrationError):
    """Registration key has already been used."""


class RegistrationKeyNotFoundError(RegistrationError):
    """Registration key was not found in the database."""


class RegistrationPermissionError(RegistrationError):
    """User does not have permission to register the bot."""


class SyncChannelsError(DiscordBotError):
    """Error during channel sync."""


class SyncChannelsPermissionError(SyncChannelsError):
    """User does not have permission to sync channels."""


class SyncChannelsServerNotFoundError(SyncChannelsError):
    """Server was not found in the database."""


class APIError(DiscordBotError):
    """Base API error."""


class APIConnectionError(APIError):
    """Failed to connect to API."""


class APITimeoutError(APIError):
    """Request timed out."""


class APIResponseError(APIError):
    """API returned an error response."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class CacheError(DiscordBotError):
    """Error during cache operations."""


class TenantNotFoundError(DiscordBotError):
    """Tenant could not be found for a guild."""


class APIKeyProvisioningError(DiscordBotError):
    """Error provisioning API key for a tenant."""
