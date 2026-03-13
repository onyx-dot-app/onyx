"""Discord-specific exception classes."""

from onyx.onyxbot.exceptions import OnyxBotError


class SyncChannelsError(OnyxBotError):
    """Error during channel sync."""
