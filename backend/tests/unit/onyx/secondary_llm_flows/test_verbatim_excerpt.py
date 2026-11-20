from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import MessageType
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import AssistantMessage, GenerationRequest, TextContent
from onyx.secondary_llm_flows import query_expansion
from onyx.secondary_llm_flows.query_expansion import extract_verbatim_excerpt
from onyx.server.metrics.internal_search import ExcerptOutcome
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tools.tool_implementations.search.constants import (
    VERBATIM_EXCERPT_MAX_CHARS,
)
from onyx.tracing.flows import LLMFlow

_SOURCE_LOOKUP = (
    "Which incident report contains 'rollback ownership transferred to storage'?"
)


def _extract(
    user_message: str, model_output: str | Exception
) -> tuple[str | None, MagicMock]:
    def invoke(
        request: GenerationRequest, context: GenerationContext | None = None
    ) -> AssistantMessage:
        # Only the latest user message reaches the model.
        assert "hello" not in str(request.messages)
        assert context is not None
        assert context.flow == LLMFlow.VERBATIM_EXCERPT_EXTRACTION
        if isinstance(model_output, Exception):
            raise model_output
        return AssistantMessage(content=[TextContent(text=model_output)])

    llm = MagicMock()
    llm.invoke.side_effect = invoke
    with patch.object(query_expansion, "record_excerpt_outcome") as record:
        excerpt = extract_verbatim_excerpt(
            [
                ChatMinimalTextMessage(message="hi", message_type=MessageType.USER),
                ChatMinimalTextMessage(
                    message="hello", message_type=MessageType.ASSISTANT
                ),
                ChatMinimalTextMessage(
                    message=user_message, message_type=MessageType.USER
                ),
            ],
            llm,
        )
    return excerpt, record


def test_copied_excerpt_is_used() -> None:
    excerpt, record = _extract(
        _SOURCE_LOOKUP, "  rollback ownership transferred to storage\n"
    )

    assert excerpt == "rollback ownership transferred to storage"
    record.assert_called_once_with(ExcerptOutcome.USED)


@pytest.mark.parametrize("model_output", ["NONE", "none", "", "   "])
def test_no_passage_to_locate(model_output: str) -> None:
    # "none" also occurs in this message, so only the sentinel check rejects it.
    excerpt, record = _extract("Who owned the rollback, if anyone?", model_output)

    assert excerpt is None
    record.assert_called_once_with(ExcerptOutcome.NONE)


@pytest.mark.parametrize(
    "model_output",
    [
        # Fabricated, re-cased, or re-punctuated text does not occur verbatim.
        "rollback ownership moved to storage",
        "Rollback ownership transferred to storage",
        "'rollback ownership transferred to storage'.",
    ],
)
def test_excerpt_not_in_the_message_is_discarded(model_output: str) -> None:
    excerpt, record = _extract(_SOURCE_LOOKUP, model_output)

    assert excerpt is None
    record.assert_called_once_with(ExcerptOutcome.INVALID)


@pytest.mark.parametrize(
    ("length", "used"),
    [(VERBATIM_EXCERPT_MAX_CHARS, True), (VERBATIM_EXCERPT_MAX_CHARS + 1, False)],
)
def test_excerpt_length_limit(length: int, used: bool) -> None:
    passage = "x" * (VERBATIM_EXCERPT_MAX_CHARS + 20)
    excerpt, _ = _extract(f"Which page says {passage}?", "x" * length)

    assert (excerpt is not None) is used


def test_failed_call_continues_without_an_excerpt() -> None:
    excerpt, record = _extract(_SOURCE_LOOKUP, RuntimeError("provider down"))

    assert excerpt is None
    record.assert_called_once_with(ExcerptOutcome.FAILED)
