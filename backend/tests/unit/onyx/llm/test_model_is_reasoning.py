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


def test_concurrent_cold_misses_probe_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent cold misses for the same model must produce a single probe
    (per-key lock), not a stampede."""
    import threading

    calls = []
    release_probe = threading.Event()

    def slow_supports_reasoning(model: str) -> bool:
        calls.append(model)
        release_probe.wait(timeout=5)
        return True

    monkeypatch.setattr(litellm, "supports_reasoning", slow_supports_reasoning)
    monkeypatch.setattr(utils, "_LITELLM_SUPPORTS_REASONING_CACHE", {})
    monkeypatch.setattr(utils, "_REASONING_PROBE_LOCKS", {})

    results: list[bool] = []
    threads = [
        threading.Thread(
            target=lambda: results.append(
                model_is_reasoning_model("cold-model", "fakeprov")
            )
        )
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    release_probe.set()
    for t in threads:
        t.join(timeout=5)

    assert results == [True, True, True, True]
    assert calls == ["fakeprov/cold-model"]


def test_probe_results_are_tenant_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two tenants can define the same custom model name for different models —
    a probe result for one tenant must never be served to another."""
    calls = []
    answers = {"tenant_a": True, "tenant_b": False}
    current_tenant = "tenant_a"

    def per_tenant_supports_reasoning(model: str) -> bool:
        calls.append((current_tenant, model))
        return answers[current_tenant]

    monkeypatch.setattr(litellm, "supports_reasoning", per_tenant_supports_reasoning)
    monkeypatch.setattr(utils, "_LITELLM_SUPPORTS_REASONING_CACHE", {})
    monkeypatch.setattr(utils, "_REASONING_PROBE_LOCKS", {})
    monkeypatch.setattr(utils, "get_current_tenant_id", lambda: current_tenant)

    assert model_is_reasoning_model("shared-name-model", "fakeprov") is True

    current_tenant = "tenant_b"
    assert model_is_reasoning_model("shared-name-model", "fakeprov") is False

    current_tenant = "tenant_a"
    assert model_is_reasoning_model("shared-name-model", "fakeprov") is True

    assert calls == [
        ("tenant_a", "fakeprov/shared-name-model"),
        ("tenant_b", "fakeprov/shared-name-model"),
    ]
