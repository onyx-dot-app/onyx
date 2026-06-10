import litellm
import pytest

from onyx.llm import utils
from onyx.llm.utils import model_is_reasoning_model


def test_model_is_reasoning_model() -> None:
    """Test that reasoning models are correctly identified and non-reasoning models are not"""

    # Models that should be identified as reasoning models
    reasoning_models = [
        ("o3", "openai"),
        ("o3-mini", "openai"),
        ("o4-mini", "openai"),
        ("deepseek-reasoner", "deepseek"),
        ("deepseek-r1", "openrouter/deepseek"),
        ("claude-sonnet-4-20250514", "anthropic"),
    ]

    # Models that should NOT be identified as reasoning models
    non_reasoning_models = [
        ("gpt-4o", "openai"),
        ("claude-3-5-sonnet-20240620", "anthropic"),
    ]

    # Test reasoning models
    for model_name, provider in reasoning_models:
        assert model_is_reasoning_model(model_name, provider) is True, (
            f"Expected {provider}/{model_name} to be identified as a reasoning model"
        )

    # Test non-reasoning models
    for model_name, provider in non_reasoning_models:
        assert model_is_reasoning_model(model_name, provider) is False, (
            f"Expected {provider}/{model_name} to NOT be identified as a reasoning model"
        )


def test_litellm_fallback_is_memoized(monkeypatch: pytest.MonkeyPatch) -> None:
    """Models missing from the local map fall back to litellm.supports_reasoning,
    which can hit the network — it must run at most once per model per process."""
    calls = []

    def fake_supports_reasoning(model: str) -> bool:
        calls.append(model)
        return True

    monkeypatch.setattr(litellm, "supports_reasoning", fake_supports_reasoning)
    monkeypatch.setattr(utils, "_LITELLM_SUPPORTS_REASONING_CACHE", {})

    assert model_is_reasoning_model("not-in-map-model", "fakeprov") is True
    assert model_is_reasoning_model("not-in-map-model", "fakeprov") is True
    assert calls == ["fakeprov/not-in-map-model"]


def test_litellm_fallback_failure_cached_with_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable host costs one attempt per TTL window (not one per
    request), but a recovered host is re-probed after the TTL instead of being
    pinned to False until process restart."""
    calls = []
    should_raise = True

    def flaky_supports_reasoning(model: str) -> bool:
        calls.append(model)
        if should_raise:
            raise ConnectionError("host unreachable")
        return True

    fake_now = 1000.0
    monkeypatch.setattr(litellm, "supports_reasoning", flaky_supports_reasoning)
    monkeypatch.setattr(utils, "_LITELLM_SUPPORTS_REASONING_CACHE", {})
    monkeypatch.setattr(utils.time, "monotonic", lambda: fake_now)

    # failure cached: second call within TTL does not re-probe
    assert model_is_reasoning_model("unreachable-model", "fakeprov") is False
    assert model_is_reasoning_model("unreachable-model", "fakeprov") is False
    assert len(calls) == 1

    # past the TTL, a recovered host is re-probed and the result is permanent
    fake_now += utils._REASONING_PROBE_FAILURE_TTL_SECONDS + 1
    should_raise = False
    assert model_is_reasoning_model("unreachable-model", "fakeprov") is True
    assert model_is_reasoning_model("unreachable-model", "fakeprov") is True
    assert len(calls) == 2
