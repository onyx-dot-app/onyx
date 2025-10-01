"""
Singleton module for litellm configuration.
This ensures litellm is configured exactly once when first imported.
All other modules should import litellm from here instead of directly.
"""

import litellm

from onyx.configs.app_configs import BRAINTRUST_ENABLED

# Import litellm

# Configure litellm settings immediately on import
# If a user configures a different model and it doesn't support all the same
# parameters like frequency and presence, just ignore them
litellm.drop_params = True
litellm.telemetry = False

if BRAINTRUST_ENABLED:
    litellm.callbacks = ["braintrust"]

# Export the configured litellm module
__all__ = ["litellm"]
