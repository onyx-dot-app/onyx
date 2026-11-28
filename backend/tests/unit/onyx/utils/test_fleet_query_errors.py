"""Failed queries report a fixed category and where the failure came from. LLM
provider failures report the provider type, never a custom provider's name."""

from unittest.mock import MagicMock, Mock

import pytest
from litellm.exceptions import (
    AuthenticationError,
    BudgetExceededError,
    ContextWindowExceededError,
    NotFoundError,
)

from onyx.chat.errors import chat_error
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.query_and_chat.streaming_models import StreamingError
from onyx.utils import fleet_query_telemetry as telemetry
from onyx.utils.fleet_telemetry import sanitize_data


@pytest.fixture
def sink(monkeypatch: pytest.MonkeyPatch) -> Mock:
    sink = Mock()
    monkeypatch.setattr(telemetry, "emit_telemetry", sink)
    return sink


def _llm(provider: str) -> MagicMock:
    llm = MagicMock()
    llm.config.model_name = "PRIVATE-deployment-name"
    llm.config.model_provider = provider
    llm.redact_error.side_effect = lambda text: text
    return llm


def _observe(packet: StreamingError, sink: Mock) -> dict[str, object]:
    observation = telemetry.QueryObservation(
        channel="web", mode=telemetry.QueryMode.CHAT
    )
    observation.observe_packet(packet)
    observation.finish()
    sink.assert_called_once()
    data: dict[str, object] = sink.call_args.args[1]
    # The sender must accept every field the observation reports.
    assert sanitize_data("query", data) is not None
    return data


@pytest.mark.parametrize(
    "error,expected",
    [
        (
            AuthenticationError("PRIVATE bad key", "openai", "gpt"),
            "auth",
        ),
        (
            NotFoundError("PRIVATE no deployment", "openai", "gpt"),
            "not_found",
        ),
        (
            ContextWindowExceededError("PRIVATE too long", "gpt", "openai"),
            "context_limit",
        ),
        (BudgetExceededError(current_cost=2.0, max_budget=1.0), "quota"),
    ],
)
def test_llm_failures_report_their_own_category(
    sink: Mock, error: Exception, expected: str
) -> None:
    packet = chat_error(error, _llm("azure"))

    data = _observe(packet, sink)

    assert data["outcome"] == "failure"
    assert data["error_code"] == expected
    assert data["error_source"] == "llm"
    assert data["llm_provider"] == "azure"


def test_llm_marker_is_not_part_of_the_chat_payload() -> None:
    packet = chat_error(
        AuthenticationError("PRIVATE bad key", "openai", "gpt"), _llm("openai")
    )

    assert "_from_llm" not in packet.model_dump()
    assert "from_llm" not in packet.model_dump_json()


def test_custom_provider_names_are_never_reported(sink: Mock) -> None:
    packet = chat_error(
        AuthenticationError("PRIVATE bad key", "openai", "gpt"),
        _llm("PRIVATE Team Gateway"),
    )

    data = _observe(packet, sink)

    assert data["llm_provider"] == "custom"


def test_same_code_from_onyx_is_not_an_llm_failure(sink: Mock) -> None:
    # NOT_FOUND is both an Onyx code and an LLM code; only the marker decides.
    packet = StreamingError(
        error="PRIVATE", error_code="NOT_FOUND", is_retryable=True, details={}
    )

    data = _observe(packet, sink)

    assert data["error_source"] == "onyx"
    assert data["llm_provider"] is None


@pytest.mark.parametrize(
    "code,expected",
    [
        (OnyxErrorCode.RATE_LIMITED, "rate_limit"),
        (OnyxErrorCode.SEAT_LIMIT_EXCEEDED, "license"),
        (OnyxErrorCode.SUBSCRIPTION_INACTIVE, "license"),
    ],
)
def test_blocking_client_errors_count_as_failures(
    sink: Mock, code: OnyxErrorCode, expected: str
) -> None:
    observation = telemetry.QueryObservation(
        channel="web", mode=telemetry.QueryMode.CHAT
    )
    observation.failed(OnyxError(code, "PRIVATE"))
    observation.finish()

    data = sink.call_args.args[1]
    assert data["outcome"] == "failure"
    assert data["error_code"] == expected
    assert data["error_source"] == "onyx"


def test_bad_input_is_still_not_a_failed_query(sink: Mock) -> None:
    observation = telemetry.QueryObservation(
        channel="web", mode=telemetry.QueryMode.CHAT
    )
    observation.failed(OnyxError(OnyxErrorCode.VALIDATION_ERROR, "PRIVATE"))
    observation.finish()

    sink.assert_not_called()
