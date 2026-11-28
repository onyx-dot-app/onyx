"""LLM gateway calls write one ``gateway.llm_request`` event with token counts
and no prompt text."""

from collections.abc import Generator
from types import SimpleNamespace
from typing import Any, cast

import pytest

from ee.onyx.tracing.audit_processor import GatewayAuditTracingProcessor
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.span_data import GenerationSpanData
from onyx.tracing.framework.spans import Span
from onyx.utils.audit import AuditEventCategory
from shared_configs.contextvars import CURRENT_USER_ID_CONTEXTVAR
from tests.utils.audit import audit_events, use_audit_settings

pytestmark = pytest.mark.usefixtures("enterprise_audit")


@pytest.fixture
def gateway_events_on(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    use_audit_settings(monkeypatch, categories=(AuditEventCategory.LLM_GATEWAY,))
    token = CURRENT_USER_ID_CONTEXTVAR.set("u-1")
    try:
        yield
    finally:
        CURRENT_USER_ID_CONTEXTVAR.reset(token)


def _span(flow: LLMFlow) -> Span[Any]:
    data = GenerationSpanData(
        input=[{"role": "user", "content": "secret prompt"}],
        output=[{"role": "assistant", "content": "secret answer"}],
        model="gpt-x",
        model_config={"flow": flow.value, "model_provider": "openai"},
        usage={"prompt_tokens": 12, "completion_tokens": 34},
    )
    return cast(Span[Any], SimpleNamespace(span_data=data, error=None))


@pytest.mark.usefixtures("gateway_events_on")
def test_gateway_call_writes_one_event(caplog: pytest.LogCaptureFixture) -> None:
    GatewayAuditTracingProcessor().on_span_end(_span(LLMFlow.LLM_GATEWAY))

    (event,) = audit_events(caplog)
    assert event["action"] == "gateway.llm_request"
    assert event["actor"]["user_id"] == "u-1"
    assert event["extra"]["model"] == "gpt-x"
    assert event["extra"]["input_tokens"] == 12
    assert event["extra"]["output_tokens"] == 34
    assert "secret" not in caplog.text


@pytest.mark.usefixtures("gateway_events_on")
def test_other_flows_write_nothing(caplog: pytest.LogCaptureFixture) -> None:
    GatewayAuditTracingProcessor().on_span_end(_span(LLMFlow.CRAFT_LLM_GENERATION))

    assert audit_events(caplog) == []
