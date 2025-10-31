"""
Singleton module for litellm configuration.
This ensures litellm is configured exactly once when first imported.
All other modules should import litellm from here instead of directly.
"""

import litellm
from agents.extensions.models.litellm_model import LitellmModel

from .config import initialize_litellm
from .monkey_patches import apply_monkey_patches

# Initialize litellm configuration immediately on import
# This ensures the singleton pattern - configuration happens only once
initialize_litellm()
apply_monkey_patches()

# Export the configured litellm module and model
__all__ = ["litellm", "LitellmModel"]
