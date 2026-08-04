import os

GATEWAY_PATH_PREFIX = "/gateway"

# Kill switch, default ON: set to "false" to send Anthropic-backed providers
# back through the translation path (losing server tools / thinking fidelity).
ANTHROPIC_GATEWAY_PASSTHROUGH_ENABLED = (
    os.environ.get("ANTHROPIC_GATEWAY_PASSTHROUGH_ENABLED", "").lower() != "false"
)
ANTHROPIC_PASSTHROUGH_CONNECT_TIMEOUT_SECONDS = 10
ANTHROPIC_PASSTHROUGH_READ_TIMEOUT_SECONDS = 600
