from typing import Any

from onyx.db.enums import HookFailStrategy
from onyx.db.enums import HookPoint
from onyx.hooks.points.base import HookPointSpec


class QueryProcessingSpec(HookPointSpec):
    """Hook point that runs on every user query before it enters the pipeline.

    Call site: inside handle_stream_message_objects() in
    backend/onyx/chat/process_message.py, immediately after message_text is
    assigned from the request and before create_new_chat_message() saves it.

    This is the earliest possible point in the query pipeline:
    - Raw query — unmodified, exactly as the user typed it
    - No side effects yet — message has not been saved to DB
    - User identity is available for user-specific logic

    Supported use cases:
    - Query rejection: block queries based on content or user context
    - Query rewriting: normalize, expand, or modify the query
    - PII removal: scrub sensitive data before the LLM sees it
    - Access control: reject queries from certain users or groups
    - Query auditing: log or track queries based on business rules
    """

    hook_point = HookPoint.QUERY_PROCESSING
    display_name = "Query Processing"
    description = (
        "Runs on every user query before it enters the pipeline. "
        "Allows rewriting, filtering, or rejecting queries."
    )
    default_timeout_seconds = 5.0  # user is actively waiting — keep tight
    fail_hard_description = (
        "The query will be blocked and the user will see an error message."
    )
    default_fail_strategy = HookFailStrategy.HARD

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The raw query string exactly as the user typed it.",
                },
                "user_email": {
                    "type": ["string", "null"],
                    "description": "Email of the user submitting the query, or null if unauthenticated.",
                },
                "chat_session_id": {
                    "type": "string",
                    "description": "UUID of the chat session. Always present — the session is guaranteed to exist by the time this hook fires.",
                },
            },
            "required": ["query", "user_email", "chat_session_id"],
            "additionalProperties": False,
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": ["string", "null"],
                    "description": (
                        "The (optionally modified) query to use. "
                        "Set to null to reject the query."
                    ),
                },
                "rejection_message": {
                    "type": ["string", "null"],
                    "description": (
                        "Message shown to the user when query is null. "
                        "Falls back to a generic message if not provided."
                    ),
                },
            },
            "required": ["query"],
        }
