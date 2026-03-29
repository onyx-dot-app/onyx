"""Constants for custom broadcast notifications."""

# GitHub source — raw URL for the notifications JSON file
CUSTOM_NOTIFICATIONS_RAW_URL = (
    "https://raw.githubusercontent.com/mbelenkiy29/privategpt-notifications/main/notifications.json"
)

FETCH_TIMEOUT = 30.0

# Redis keys (in shared namespace)
REDIS_KEY_PREFIX = "custom_notifications:"
REDIS_KEY_FETCHED_AT = f"{REDIS_KEY_PREFIX}fetched_at"
REDIS_KEY_ETAG = f"{REDIS_KEY_PREFIX}etag"

# Cache TTL: 24 hours
REDIS_CACHE_TTL = 60 * 60 * 24

# Auto-refresh threshold: 5 minutes
AUTO_REFRESH_THRESHOLD_SECONDS = 60 * 5
