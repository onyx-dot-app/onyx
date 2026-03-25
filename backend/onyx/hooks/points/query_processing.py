from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from onyx.db.enums import HookFailStrategy
from onyx.db.enums import HookPoint
from onyx.hooks.points.base import HookPointSpec


class QueryProcessingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(description="The raw query string exactly as the user typed it.")
    user_email: str | None = Field(
        description="Email of the user submitting the query, or null if unauthenticated."
    )
    chat_session_id: str = Field(
        description="UUID of the chat session, formatted as a hyphenated lowercase string (e.g. '550e8400-e29b-41d4-a716-446655440000'). Always present — the session is guaranteed to exist by the time this hook fires."
    )


class QueryProcessingResponse(BaseModel):
    # Intentionally permissive — customer endpoints may return extra fields.
    query: str | None = Field(
        default=None,
        description=(
            "The query to use in the pipeline. "
            "Null, empty string, whitespace-only, or absent = reject the query."
        ),
    )
    rejection_message: str | None = Field(
        default=None,
        description="Message shown to the user when the query is rejected. Falls back to a generic message if not provided.",
    )


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
    # TODO(Bo-Onyx): update later
    docs_url = "https://docs.google.com/document/d/1pGhB8Wcnhhj8rS4baEJL6CX05yFhuIDNk1gbBRiWu94/edit?tab=t.g2r1a1699u87"

    payload_model = QueryProcessingPayload
    response_model = QueryProcessingResponse
