"""
Singleton module for litellm configuration.
This ensures litellm is configured exactly once when first imported.
All other modules should import litellm from here instead of directly.
"""

import litellm
from agents.extensions.models.litellm_model import LitellmModel

# Export the configured litellm module and model
__all__ = ["litellm", "LitellmModel"]
