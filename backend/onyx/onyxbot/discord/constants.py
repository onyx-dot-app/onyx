"""Discord bot constants."""

# API settings
API_REQUEST_TIMEOUT: int = 3 * 60  # 3 minutes

# Cache settings
CACHE_REFRESH_INTERVAL: int = 60  # 1 minute

# Message settings
MAX_MESSAGE_LENGTH: int = 2000  # Discord's character limit
MAX_CONTEXT_MESSAGES: int = 10  # Max messages to include in conversation context
# Note: Discord.py's add_reaction() requires unicode emoji, not :name: format
THINKING_EMOJI: str = "🤔"  # U+1F914 - Thinking Face
SUCCESS_EMOJI: str = "✅"  # U+2705 - White Heavy Check Mark
ERROR_EMOJI: str = "❌"  # U+274C - Cross Mark

# Attachment settings
# Discord allows at most 10 attachments per message, so this never truncates a
# single real message; it only bounds work if that limit ever changes.
MAX_ATTACHMENTS_PER_MESSAGE: int = 10
# Per-file and per-message download budgets. The bot is a single replica that
# buffers attachments in memory before forwarding them, so these caps exist to
# protect the bot process, independently of the (larger) server-side upload
# limit. Boosted guilds allow uploads well beyond this.
MAX_ATTACHMENT_BYTES: int = 20 * 1024 * 1024  # 20 MB
MAX_TOTAL_ATTACHMENT_BYTES: int = 40 * 1024 * 1024  # 40 MB

# Command prefix
REGISTER_COMMAND: str = "register"
SYNC_CHANNELS_COMMAND: str = "sync-channels"
