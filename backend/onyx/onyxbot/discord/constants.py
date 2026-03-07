"""Discord-specific bot constants.

Shared constants (API_REQUEST_TIMEOUT, CACHE_REFRESH_INTERVAL,
REGISTER_COMMAND) live in ``onyx.onyxbot.constants``.
"""

# Message settings
MAX_MESSAGE_LENGTH: int = 2000  # Discord's character limit
MAX_CONTEXT_MESSAGES: int = 10  # Max messages to include in conversation context
# Note: Discord.py's add_reaction() requires unicode emoji, not :name: format
THINKING_EMOJI: str = "\U0001f914"  # U+1F914 - Thinking Face
SUCCESS_EMOJI: str = "\u2705"  # U+2705 - White Heavy Check Mark
ERROR_EMOJI: str = "\u274c"  # U+274C - Cross Mark

# Discord-specific commands
SYNC_CHANNELS_COMMAND: str = "sync-channels"
