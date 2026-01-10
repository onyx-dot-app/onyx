"""Constants for release notes functionality."""

# GitHub source
GITHUB_RAW_BASE_URL = (
    "https://raw.githubusercontent.com/onyx-dot-app/documentation/main"
)
GITHUB_CHANGELOG_RAW_URL = f"{GITHUB_RAW_BASE_URL}/changelog.mdx"

# Base URL for changelog documentation (used for notification links)
DOCS_CHANGELOG_BASE_URL = "https://docs.onyx.app/changelog"

FETCH_TIMEOUT = 60.0

# Redis keys (in shared namespace)
REDIS_KEY_PREFIX = "release_notes:"
REDIS_KEY_FETCHED_AT = f"{REDIS_KEY_PREFIX}fetched_at"
REDIS_KEY_ETAG = f"{REDIS_KEY_PREFIX}etag"

# Cache TTL: 24 hours
REDIS_CACHE_TTL = 60 * 60 * 24

# Auto-refresh threshold: 1 hour
AUTO_REFRESH_THRESHOLD_SECONDS = 60 * 60
