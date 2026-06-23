from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.configs.chat_configs import SECONDARY_LLM_FLOW_TIMEOUT_S
from onyx.context.search.models import ContextExpansionType
from onyx.llm.interfaces import LLM
from onyx.llm.multi_llm import LLMTimeoutError
from onyx.secondary_llm_flows.document_filter import classify_section_relevance


@contextmanager
def _noop_span() -> Iterator[MagicMock]:
    yield MagicMock()


def _make_llm(invoke: MagicMock) -> LLM:
    llm = MagicMock(spec=LLM)
    llm.invoke = invoke
    return llm


@patch("onyx.secondary_llm_flows.document_filter.record_llm_response")
@patch(
    "onyx.secondary_llm_flows.document_filter.llm_generation_span",
    return_value=_noop_span(),
)
def test_classify_section_relevance_timeout_falls_back(
    _span: MagicMock, _record: MagicMock
) -> None:
    """A timed-out classification call must degrade to the safe default instead
    of propagating, so a stalled provider can't hang the worker."""
    invoke = MagicMock(side_effect=LLMTimeoutError("timed out"))
    llm = _make_llm(invoke)

    result = classify_section_relevance(
        document_title="Doc",
        section_text="body",
        user_query="q",
        llm=llm,
        # surrounding text present so the no-context post-adjustment is not applied
        section_above_text="above",
        section_below_text="below",
    )

    assert result == ContextExpansionType.MAIN_SECTION_ONLY
    # the bound that makes the call fail fast must actually be passed through
    assert invoke.call_args.kwargs["timeout_override"] == SECONDARY_LLM_FLOW_TIMEOUT_S


@patch("onyx.secondary_llm_flows.document_filter.record_llm_response")
@patch(
    "onyx.secondary_llm_flows.document_filter.llm_generation_span",
    return_value=_noop_span(),
)
def test_classify_section_relevance_passes_timeout_on_success(
    _span: MagicMock, _record: MagicMock
) -> None:
    response = MagicMock()
    response.choice.message.content = "3"  # FULL_DOCUMENT
    invoke = MagicMock(return_value=response)
    llm = _make_llm(invoke)

    result = classify_section_relevance(
        document_title="Doc",
        section_text="body",
        user_query="q",
        llm=llm,
        section_above_text="above",
        section_below_text="below",
    )

    assert result == ContextExpansionType.FULL_DOCUMENT
    assert invoke.call_args.kwargs["timeout_override"] == SECONDARY_LLM_FLOW_TIMEOUT_S
