import hashlib
import re

# Bedrock rejects toolUse.name values that don't match [a-zA-Z0-9_-]+, and
# OpenAI imposes the same constraint on function names. User-supplied Tool.name
# and OpenAPI operationId can contain spaces, dots, etc.
_INVALID_TOOL_NAME_CHARS = re.compile(r"[^a-zA-Z0-9_-]")
# OpenAI function names are limited to 64 ASCII characters.
MAX_TOOL_NAME_LENGTH = 64
_TOOL_NAME_HASH_LENGTH = 12


def sanitize_tool_name(name: str) -> str:
    return _INVALID_TOOL_NAME_CHARS.sub("_", name)


def normalize_external_tool_name(qualified: str) -> str:
    """Keep external tool identities distinct after sanitation or truncation."""
    sanitized = sanitize_tool_name(qualified)
    if sanitized == qualified and len(sanitized) <= MAX_TOOL_NAME_LENGTH:
        return sanitized
    digest = hashlib.sha256(qualified.encode()).hexdigest()[:_TOOL_NAME_HASH_LENGTH]
    prefix_length = MAX_TOOL_NAME_LENGTH - len(digest) - 1
    return f"{sanitized[:prefix_length]}_{digest}"


# The action key of a request to an app that is no catalog action
# (``WHOLE_DOMAIN_ACTION_TYPE``).
_OTHER_REQUESTS_ACTION = "unspecified"


def custom_tool_name(integration_id: int, operation_id: str) -> str:
    """The chat tool of one REST operation or GraphQL root field. A GraphQL
    key (``query.<field>``) loses its dot, so the name needs no hash."""
    operation_id = re.sub(r"^(query|mutation)\.", r"\1_", operation_id)
    return normalize_external_tool_name(f"custom__{integration_id}__{operation_id}")


def app_action_tool_name(integration_id: int, action_key: str) -> str:
    """The chat tool of one action of a preset."""
    suffix = (
        "request"
        if action_key == _OTHER_REQUESTS_ACTION
        else action_key.replace(".", "_")
    )
    return normalize_external_tool_name(f"app__{integration_id}__{suffix}")
