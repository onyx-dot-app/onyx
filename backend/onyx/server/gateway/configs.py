import os

from onyx.server.settings.models import Tier

GATEWAY_PATH_PREFIX = "/gateway"
LLM_GATEWAY_MIN_TIER = Tier.BUSINESS

# Kill switch, default ON: set to "false" to send Anthropic-backed providers
# back through the translation path (losing server tools / thinking fidelity).
ANTHROPIC_GATEWAY_PASSTHROUGH_ENABLED = (
    os.environ.get("ANTHROPIC_GATEWAY_PASSTHROUGH_ENABLED", "").lower() != "false"
)
ANTHROPIC_PASSTHROUGH_CONNECT_TIMEOUT_SECONDS = 10
ANTHROPIC_PASSTHROUGH_READ_TIMEOUT_SECONDS = 600

# Kill switch, default ON: set to "false" to send true-OpenAI models back
# through the translation path (losing hosted tools / encrypted reasoning).
OPENAI_GATEWAY_PASSTHROUGH_ENABLED = (
    os.environ.get("OPENAI_GATEWAY_PASSTHROUGH_ENABLED", "").lower() != "false"
)
OPENAI_PASSTHROUGH_CONNECT_TIMEOUT_SECONDS = 10
OPENAI_PASSTHROUGH_READ_TIMEOUT_SECONDS = 600
