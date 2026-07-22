from unittest.mock import MagicMock, patch

from onyx.configs.chat_configs import SECONDARY_LLM_FLOW_TIMEOUT_S
from onyx.configs.constants import MessageType
from onyx.secondary_llm_flows.query_expansion import (
    keyword_query_expansion,
    semantic_query_rephrase,
)
from onyx.tools.models import ChatMinimalTextMessage
from tests.unit.onyx.secondary_llm_flows.conftest import make_llm, noop_span


def _make_history() -> list[ChatMinimalTextMessage]:
    return [
        ChatMinimalTextMessage(
            message="Find recent onboarding docs.",
            message_type=MessageType.USER,
        )
    ]


def _make_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choice.message.content = content
    return response


@patch("onyx.secondary_llm_flows.query_expansion.record_llm_response")
@patch(
    "onyx.secondary_llm_flows.query_expansion.llm_generation_span",
    return_value=noop_span(),
)
def test_semantic_query_rephrase_passes_timeout(
    _span: MagicMock, _record: MagicMock
) -> None:
    invoke = MagicMock(return_value=_make_response("onboarding documentation"))
    llm = make_llm(invoke)

    result = semantic_query_rephrase(_make_history(), llm)

    assert result == "onboarding documentation"
    assert invoke.call_args.kwargs["timeout_override"] == SECONDARY_LLM_FLOW_TIMEOUT_S


@patch("onyx.secondary_llm_flows.query_expansion.record_llm_response")
@patch(
    "onyx.secondary_llm_flows.query_expansion.llm_generation_span",
    return_value=noop_span(),
)
def test_keyword_query_expansion_passes_timeout(
    _span: MagicMock, _record: MagicMock
) -> None:
    invoke = MagicMock(return_value=_make_response("onboarding docs\nnew hire guide"))
    llm = make_llm(invoke)

    result = keyword_query_expansion(_make_history(), llm)

    assert result == ["onboarding docs", "new hire guide"]
    assert invoke.call_args.kwargs["timeout_override"] == SECONDARY_LLM_FLOW_TIMEOUT_S
