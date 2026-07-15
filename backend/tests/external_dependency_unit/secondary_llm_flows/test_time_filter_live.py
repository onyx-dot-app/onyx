"""Live behavior test for the time-filter secondary LLM flow.

Exercises `decide_time_filter` against a real (cheap) model to confirm the
prompt + JSON parsing reliably turn natural-language time references into the
right kind of `TimeFilter`. Boundary dates are asserted loosely (the model does
the relative-date math); only the *shape* of the decision is asserted strictly.
"""

import pytest

from onyx.configs.constants import MessageType
from onyx.llm.constants import LlmProviderNames
from onyx.llm.multi_llm import LitellmLLM
from onyx.secondary_llm_flows.time_filter import decide_time_filter
from onyx.secondary_llm_flows.time_filter import DocumentTimeField
from onyx.tools.models import ChatMinimalTextMessage
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.nightly


def _build_llm(api_key: str) -> LitellmLLM:
    return LitellmLLM(
        api_key=api_key,
        model_provider=LlmProviderNames.OPENAI,
        model_name="gpt-5-mini",
        max_input_tokens=128_000,
        timeout=60,
    )


def _history(message: str) -> list[ChatMinimalTextMessage]:
    return [ChatMinimalTextMessage(message=message, message_type=MessageType.USER)]


@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
def test_relative_cutoff_sets_a_lower_bound(
    test_secrets: dict[TestSecret, str],
) -> None:
    llm = _build_llm(test_secrets[TestSecret.OPENAI_API_KEY])
    tf = decide_time_filter(
        _history("What changed in the codebase in the last week?"), llm
    )
    assert tf is not None
    assert tf.start is not None
    # "changed" is an update-time reference.
    assert tf.field is DocumentTimeField.UPDATED_AT


@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
def test_creation_phrasing_targets_created_field(
    test_secrets: dict[TestSecret, str],
) -> None:
    """A creation reference ("sent") scopes on created_at, not last_updated."""
    llm = _build_llm(test_secrets[TestSecret.OPENAI_API_KEY])
    tf = decide_time_filter(_history("Find Slack messages sent in January 2025."), llm)
    assert tf is not None
    assert tf.field is DocumentTimeField.CREATED_AT
    assert tf.start is not None and tf.start.date().isoformat() == "2025-01-01"


@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
def test_single_day_is_a_bounded_range(
    test_secrets: dict[TestSecret, str],
) -> None:
    llm = _build_llm(test_secrets[TestSecret.OPENAI_API_KEY])
    tf = decide_time_filter(_history("Show me notes from the 25th of March 2024."), llm)
    assert tf is not None
    assert tf.start is not None and tf.end is not None
    assert tf.start.date().isoformat() == "2024-03-25"
    assert tf.end.date().isoformat() == "2024-03-25"


@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
def test_named_month_is_a_bounded_range(
    test_secrets: dict[TestSecret, str],
) -> None:
    llm = _build_llm(test_secrets[TestSecret.OPENAI_API_KEY])
    tf = decide_time_filter(_history("What did we ship in January 2025?"), llm)
    assert tf is not None
    assert tf.start is not None and tf.end is not None
    assert tf.start.date().isoformat() == "2025-01-01"
    assert tf.end.date().month == 1


@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
def test_latest_is_not_a_hard_range(
    test_secrets: dict[TestSecret, str],
) -> None:
    """A vague freshness preference must not invent a hard date boundary."""
    llm = _build_llm(test_secrets[TestSecret.OPENAI_API_KEY])
    tf = decide_time_filter(_history("What's the latest on the billing project?"), llm)
    # Either no filter or favor_recent — but never a concrete bounded range.
    assert tf is None or (tf.start is None and tf.end is None)


@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
def test_no_time_reference_yields_no_filter(
    test_secrets: dict[TestSecret, str],
) -> None:
    llm = _build_llm(test_secrets[TestSecret.OPENAI_API_KEY])
    tf = decide_time_filter(_history("How do I configure SSO for our workspace?"), llm)
    assert tf is None
