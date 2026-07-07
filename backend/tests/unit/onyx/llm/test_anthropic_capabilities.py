"""Tests for capability-driven resolution of Anthropic thinking/sampling
contracts.

Both resolution branches are covered: the litellm-registry branch (flags
present in litellm.model_cost) and the hardcoded-tuple fallback branch
(model absent from the registry, e.g. proxy aliases or stale bundled maps).
"""

from unittest.mock import patch

import pytest

from onyx.llm.anthropic_capabilities import anthropic_omits_sampling_params
from onyx.llm.anthropic_capabilities import anthropic_requires_adaptive_thinking
from onyx.llm.anthropic_capabilities import anthropic_supports_adaptive_thinking

# ---------------------------------------------------------------------------
# Registry branch — real litellm bundled map
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_name",
    [
        "claude-sonnet-5",
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-fable-5",
        # Provider-prefixed and regional variants present in the registry
        "anthropic/claude-sonnet-5",
        "us.anthropic.claude-sonnet-5",
        "vertex_ai/claude-sonnet-5",
    ],
)
def test_new_contract_models_resolve_via_registry(model_name: str) -> None:
    # Disable the fallback so a pass proves the registry branch fired.
    with patch("onyx.llm.anthropic_capabilities._matches_fallback", return_value=False):
        assert anthropic_requires_adaptive_thinking(model_name)
        assert anthropic_supports_adaptive_thinking(model_name)
        assert anthropic_omits_sampling_params(model_name)


def test_sonnet_4_6_supports_adaptive_but_keeps_legacy_paths() -> None:
    # Sonnet 4.6 accepts adaptive thinking but still accepts the legacy
    # thinking API and sampling params — it must not be treated as a
    # new-contract model.
    assert anthropic_supports_adaptive_thinking("claude-sonnet-4-6")
    assert not anthropic_requires_adaptive_thinking("claude-sonnet-4-6")
    assert not anthropic_omits_sampling_params("claude-sonnet-4-6")


@pytest.mark.parametrize("model_name", ["claude-3-5-sonnet", "claude-sonnet-4-5"])
def test_older_sonnet_models_are_unaffected(model_name: str) -> None:
    assert not anthropic_requires_adaptive_thinking(model_name)
    assert not anthropic_supports_adaptive_thinking(model_name)
    assert not anthropic_omits_sampling_params(model_name)


def test_future_model_with_registry_flags_needs_no_code_change() -> None:
    # A hypothetical future Anthropic model that ships with correct flags in
    # the litellm registry must resolve without touching Onyx code.
    synthetic_entry = {
        "claude-saga-6": {
            "litellm_provider": "anthropic",
            "supports_adaptive_thinking": True,
            "supports_sampling_params": False,
        }
    }
    from onyx.llm.litellm_singleton import litellm

    with patch.dict(litellm.model_cost, synthetic_entry):
        assert anthropic_requires_adaptive_thinking("claude-saga-6")
        assert anthropic_supports_adaptive_thinking("claude-saga-6")
        assert anthropic_omits_sampling_params("claude-saga-6")


# ---------------------------------------------------------------------------
# Fallback branch — model absent from the registry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_name",
    [
        # Aliases a litellm_proxy admin might configure — absent from the
        # registry, resolved by tuple substring match.
        "litellm_proxy/my-claude-sonnet-5-alias",
        "claude-sonnet-5@20260101",
        "claude-5-sonnet",
        "claude-4.8-opus",
    ],
)
def test_unmapped_new_contract_variants_resolve_via_fallback(
    model_name: str,
) -> None:
    with patch(
        "onyx.llm.anthropic_capabilities._litellm_capability_flags",
        return_value=(None, None),
    ):
        assert anthropic_requires_adaptive_thinking(model_name)
        assert anthropic_omits_sampling_params(model_name)


class _RaisingDict(dict):
    def get(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError("registry unavailable")


def test_registry_lookup_failure_falls_back_to_tuples() -> None:
    # A broken/unavailable registry must degrade to the fallback tuples, not
    # raise or change behavior for known models.
    from onyx.llm.litellm_singleton import litellm

    with patch.object(litellm, "model_cost", _RaisingDict()):
        assert anthropic_requires_adaptive_thinking("claude-sonnet-5")
        assert anthropic_omits_sampling_params("claude-sonnet-5")
        assert not anthropic_requires_adaptive_thinking("claude-sonnet-4-5")


def test_explicit_registry_answer_beats_colliding_fallback_substring() -> None:
    # A future model whose name contains a new-contract substring but whose
    # registry entry explicitly supports sampling / rejects adaptive must
    # follow the registry, not the substring match.
    entry = {
        "claude-opus-4-7-pro": {
            "supports_adaptive_thinking": False,
            "supports_sampling_params": True,
        }
    }
    from onyx.llm.litellm_singleton import litellm

    with patch.dict(litellm.model_cost, entry):
        assert not anthropic_requires_adaptive_thinking("claude-opus-4-7-pro")
        assert not anthropic_supports_adaptive_thinking("claude-opus-4-7-pro")
        assert not anthropic_omits_sampling_params("claude-opus-4-7-pro")


def test_runtime_map_refresh_is_picked_up() -> None:
    # litellm can refresh its model map at runtime; a model that was missing
    # must resolve via the registry once the refreshed map contains it.
    from onyx.llm.litellm_singleton import litellm

    with patch.object(litellm, "model_cost", {}):
        assert not anthropic_requires_adaptive_thinking("claude-saga-6")

    refreshed = {
        "claude-saga-6": {
            "supports_adaptive_thinking": True,
            "supports_sampling_params": False,
        }
    }
    with patch.object(litellm, "model_cost", refreshed):
        assert anthropic_requires_adaptive_thinking("claude-saga-6")


def test_unknown_model_defaults_to_legacy_behavior() -> None:
    assert not anthropic_requires_adaptive_thinking("some-unrelated-model")
    assert not anthropic_supports_adaptive_thinking("some-unrelated-model")
    assert not anthropic_omits_sampling_params("some-unrelated-model")
