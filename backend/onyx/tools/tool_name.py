import re

# Bedrock rejects toolUse.name values that don't match [a-zA-Z0-9_-]+, and
# OpenAI imposes the same constraint on function names. User-supplied Tool.name
# and OpenAPI operationId can contain spaces, dots, etc.
_INVALID_TOOL_NAME_CHARS = re.compile(r"[^a-zA-Z0-9_-]")


def sanitize_tool_name(name: str) -> str:
    return _INVALID_TOOL_NAME_CHARS.sub("_", name)
