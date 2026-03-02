"""Teams-specific bot constants.

Shared constants (API_REQUEST_TIMEOUT, CACHE_REFRESH_INTERVAL,
REGISTER_COMMAND) live in ``onyx.onyxbot.constants``.
"""

# Bot Framework settings
BOT_MESSAGES_ENDPOINT: str = "/api/messages"
BOT_HEALTH_ENDPOINT: str = "/health"

# Adaptive Card settings
ADAPTIVE_CARD_SCHEMA: str = "http://adaptivecards.io/schemas/adaptive-card.json"
ADAPTIVE_CARD_VERSION: str = "1.3"  # Compatible with mobile clients
MAX_CITATIONS: int = 5
