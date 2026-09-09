from unittest.mock import Mock, patch

import pytest

from onyx.chat.token_budget import ChatTokenBudget, resolve_chat_token_budget
from onyx.configs.model_configs import GEN_AI_MODEL_FALLBACK_MAX_TOKENS
from onyx.llm.interfaces import LLMConfig


@pytest.fixture(autouse=True)
def pin_answer_reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.chat.token_budget.GEN_AI_NUM_RESERVED_OUTPUT_TOKENS", 1024
    )


def _llm(
    *,
    provider: str = "openai",
    model: str = "gpt-5.6-sol",
    deployment: str | None = None,
    max_input_tokens: int = 1_000_000,
) -> Mock:
    llm = Mock()
    llm.config = LLMConfig(
        model_provider=provider,
        model_name=model,
        temperature=0,
        deployment_name=deployment,
        max_input_tokens=max_input_tokens,
    )
    return llm


def test_resolves_separate_input_output_and_context_caps() -> None:
    with (
        patch("onyx.chat.token_budget.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", 0.05),
        patch(
            "onyx.chat.token_budget.get_model_map",
            return_value={
                "openai/gpt-5.6-sol": {
                    "max_input_tokens": 922_000,
                    "max_output_tokens": 128_000,
                    "max_context_tokens": 1_050_000,
                }
            },
        ),
    ):
        budget = resolve_chat_token_budget(_llm())

    assert budget.input_tokens == 875_900
    assert budget.safety_tokens == 46_100
    assert budget.max_output_tokens == 128_000
    assert budget.context_tokens == 1_050_000
    assert budget.output_allowance(estimated_input_tokens=875_900) == 128_000


def test_context_falls_back_to_metadata_input_for_shared_context_models() -> None:
    with (
        patch("onyx.chat.token_budget.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", 0.05),
        patch(
            "onyx.chat.token_budget.get_model_map",
            return_value={
                "anthropic/claude-sonnet-5": {
                    "max_input_tokens": 200_000,
                    "max_output_tokens": 64_000,
                }
            },
        ),
    ):
        budget = resolve_chat_token_budget(
            _llm(provider="anthropic", model="claude-sonnet-5")
        )

    assert budget.input_tokens == 129_200
    assert budget.safety_tokens == 6_800
    assert budget.context_tokens == 200_000
    assert budget.output_allowance(estimated_input_tokens=129_200) == 64_000


def test_operator_input_cap_does_not_reduce_full_output_allowance() -> None:
    with (
        patch("onyx.chat.token_budget.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", 0.05),
        patch(
            "onyx.chat.token_budget.get_model_map",
            return_value={
                "anthropic/claude-sonnet-5": {
                    "max_input_tokens": 200_000,
                    "max_output_tokens": 64_000,
                }
            },
        ),
    ):
        budget = resolve_chat_token_budget(
            _llm(
                provider="anthropic",
                model="claude-sonnet-5",
                max_input_tokens=8_000,
            )
        )

    assert budget.input_tokens == 7_600
    assert budget.safety_tokens == 400
    assert budget.output_allowance(estimated_input_tokens=7_600) == 64_000


def test_malformed_context_uses_metadata_input_as_conservative_context() -> None:
    with (
        patch("onyx.chat.token_budget.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", 0),
        patch(
            "onyx.chat.token_budget.get_model_map",
            return_value={
                "openai/weird-context": {
                    "max_input_tokens": 100_000,
                    "max_output_tokens": 10_000,
                    "max_context_tokens": "100000",
                }
            },
        ),
    ):
        budget = resolve_chat_token_budget(_llm(model="weird-context"))

    assert budget.input_tokens == 90_000
    assert budget.context_tokens == 100_000


def test_explicit_context_smaller_than_input_constrains_input_budget() -> None:
    with (
        patch("onyx.chat.token_budget.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", 0),
        patch(
            "onyx.chat.token_budget.get_model_map",
            return_value={
                "openai/small-context": {
                    "max_input_tokens": 100_000,
                    "max_output_tokens": 10_000,
                    "max_context_tokens": 50_000,
                }
            },
        ),
    ):
        budget = resolve_chat_token_budget(_llm(model="small-context"))

    assert budget.input_tokens == 40_000
    assert budget.output_allowance(estimated_input_tokens=40_000) == 10_000


@pytest.mark.parametrize(
    "model_map",
    [
        {},
        {"openai/custom": {"max_input_tokens": 128_000}},
        {"openai/custom": {"max_output_tokens": 16_000}},
        {"openai/custom": {"max_input_tokens": True, "max_output_tokens": 16_000}},
        {"openai/custom": {"max_input_tokens": 128_000, "max_output_tokens": False}},
        {"openai/custom": {"max_tokens": 128_000, "max_output_tokens": 16_000}},
    ],
)
def test_legacy_fallback_when_explicit_metadata_is_missing_or_invalid(
    model_map: dict,
) -> None:
    with (
        patch("onyx.chat.token_budget.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", 0.05),
        patch("onyx.chat.token_budget.get_model_map", return_value=model_map),
    ):
        budget = resolve_chat_token_budget(
            _llm(model="custom", max_input_tokens=GEN_AI_MODEL_FALLBACK_MAX_TOKENS)
        )

    assert budget.input_tokens == 30_400
    assert budget.safety_tokens == 1_600
    assert budget.max_output_tokens is None
    assert budget.context_tokens is None
    assert budget.output_allowance(estimated_input_tokens=1) is None


def test_deployment_alias_is_used_after_configured_model_name() -> None:
    with (
        patch("onyx.chat.token_budget.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", 0.05),
        patch(
            "onyx.chat.token_budget.get_model_map",
            return_value={
                "azure/deployment-alias": {
                    "max_input_tokens": 128_000,
                    "max_output_tokens": 16_000,
                }
            },
        ),
    ):
        budget = resolve_chat_token_budget(
            _llm(
                provider="azure", model="configured-name", deployment="deployment-alias"
            )
        )

    assert budget.input_tokens == 106_400
    assert budget.max_output_tokens == 16_000


def test_matching_uses_requested_provider_before_bare_model_name() -> None:
    with (
        patch("onyx.chat.token_budget.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", 0),
        patch(
            "onyx.chat.token_budget.get_model_map",
            return_value={
                "azure/gpt-5": {
                    "max_input_tokens": 100_000,
                    "max_output_tokens": 10_000,
                },
                "gpt-5": {
                    "max_input_tokens": 200_000,
                    "max_output_tokens": 20_000,
                },
            },
        ),
    ):
        budget = resolve_chat_token_budget(_llm(provider="azure", model="openai/gpt-5"))

    assert budget.input_tokens == 90_000
    assert budget.max_output_tokens == 10_000
    assert budget.context_tokens == 100_000


def test_complete_alias_record_is_used_when_model_metadata_is_partial() -> None:
    with (
        patch("onyx.chat.token_budget.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", 0),
        patch(
            "onyx.chat.token_budget.get_model_map",
            return_value={
                "openai/configured-name": {"max_input_tokens": 100_000},
                "openai/deployment-alias": {
                    "max_input_tokens": 200_000,
                    "max_output_tokens": 20_000,
                },
            },
        ),
    ):
        budget = resolve_chat_token_budget(
            _llm(
                model="configured-name",
                deployment="deployment-alias",
                max_input_tokens=100_000,
            )
        )

    assert budget.max_output_tokens == 20_000
    assert budget.context_tokens == 200_000
    assert budget.input_tokens == 100_000


def test_full_output_reserve_must_fit_context() -> None:
    with (
        patch("onyx.chat.token_budget.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", 0.05),
        patch(
            "onyx.chat.token_budget.get_model_map",
            return_value={
                "openai/tiny": {
                    "max_input_tokens": 4_000,
                    "max_output_tokens": 4_000,
                }
            },
        ),
    ):
        budget = resolve_chat_token_budget(_llm(model="tiny", max_input_tokens=4_000))

    assert budget.input_tokens == 3_800
    assert budget.max_output_tokens is None
    assert budget.context_tokens is None


@pytest.mark.parametrize("estimated_input_tokens", [95, 100, 200])
def test_output_allowance_keeps_legacy_fallback_when_context_is_exhausted(
    estimated_input_tokens: int,
) -> None:
    budget = ChatTokenBudget(
        input_tokens=95,
        max_output_tokens=10,
        context_tokens=100,
        safety_tokens=5,
    )

    assert (
        budget.output_allowance(estimated_input_tokens=estimated_input_tokens) is None
    )
