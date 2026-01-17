"""Discord bot constants."""

# API settings
API_REQUEST_TIMEOUT: int = 3 * 60  # 3 minutes

# Cache settings
CACHE_REFRESH_INTERVAL: int = 60  # 1 minute

# Message settings
MAX_MESSAGE_LENGTH: int = 2000  # Discord's character limit
# Note: Discord.py's add_reaction() requires unicode emoji, not :name: format
THINKING_EMOJI: str = "🤔"  # U+1F914 - Thinking Face
SUCCESS_EMOJI: str = "✅"  # U+2705 - White Heavy Check Mark
ERROR_EMOJI: str = "❌"  # U+274C - Cross Mark

# Command prefix
REGISTER_COMMAND: str = "register"
SYNC_CHANNELS_COMMAND: str = "sync-channels"

# Discord bot service API key name
DISCORD_SERVICE_API_KEY_NAME: str = "discord-bot-service"
REGISTRATION_KEY_PREFIX: str = "discord_"
