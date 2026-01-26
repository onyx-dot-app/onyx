"""
Feature flag keys used throughout the application.
Centralizes feature flag key definitions to avoid magic strings.
"""

# Build Mode feature flag - controls access to /build routes and features
# When disabled via PostHog, all build routes return 404
BUILD_MODE_ENABLED = "build-mode-enabled"
