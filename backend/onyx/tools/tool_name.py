import hashlib
import re

from onyx.external_apps.models import OTHER_REQUEST_ACTION_KEY

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


# Saved chats keep tool names, so the prefixes ``custom__`` and ``app__`` stay.


def api_app_tool_name(integration_id: int, operation_id: str) -> str:
    """The chat tool of one REST operation or GraphQL root field. A GraphQL
    key (``query.<field>``) loses its dot, so the name needs no hash."""
    operation_id = re.sub(r"^(query|mutation)\.", r"\1_", operation_id)
    return normalize_external_tool_name(f"custom__{integration_id}__{operation_id}")


def preset_tool_name(integration_id: int, action_key: str) -> str:
    """The chat tool of one action of a preset. The other-request action
    gives ``app__<id>__request``."""
    suffix = (
        "request"
        if action_key == OTHER_REQUEST_ACTION_KEY
        else action_key.replace(".", "_")
    )
    return normalize_external_tool_name(f"app__{integration_id}__{suffix}")


def connect_tool_name(integration_id: int) -> str:
    """The one chat tool of an app that the user has not connected."""
    return normalize_external_tool_name(f"app__{integration_id}__connect")
