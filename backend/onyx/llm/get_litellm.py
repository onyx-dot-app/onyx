"""Module for configuring the litellm module."""

from onyx.configs.app_configs import BRAINTRUST_ENABLED

# Track whether litellm has been configured
_litellm_configured = False


def configure_litellm() -> None:
    """Configure the litellm module settings. Must be called before using litellm."""
    global _litellm_configured
    if _litellm_configured:
        return

    import litellm

    # If a user configures a different model and it doesn't support all the same
    # parameters like frequency and presence, just ignore them
    litellm.drop_params = True
    litellm.telemetry = False

    if BRAINTRUST_ENABLED:
        litellm.callbacks = ["braintrust"]

    _litellm_configured = True
