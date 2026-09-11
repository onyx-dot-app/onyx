from unittest.mock import Mock

import pytest

from onyx.chat.token_budget import ChatTokenBudget, resolve_chat_token_budget
from onyx.configs.model_configs import GEN_AI_MODEL_FALLBACK_MAX_TOKENS
from onyx.llm.interfaces import LLMConfig

ModelMap = dict[str, dict[str, object]]


@pytest.fixture
def model_map(monkeypatch: pytest.MonkeyPatch) -> ModelMap:
    models: ModelMap = {}
    monkeypatch.setattr("onyx.chat.token_budget.get_model_map", lambda: models)
    monkeypatch.setattr("onyx.chat.token_budget.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", 0.05)
    monkeypatch.setattr(
        "onyx.chat.token_budget.GEN_AI_NUM_RESERVED_OUTPUT_TOKENS", 1024
    )
    return models


@pytest.fixture
def llm() -> Mock:
    return Mock(
        config=LLMConfig(
            model_provider="openai",
            model_name="model",
            temperature=0,
            max_input_tokens=1_000_000,
        )
    )


@pytest.mark.parametrize(
    "limits,input_config,outputs",
    [
        (
            (922_000, 128_000, 1_050_000),
            (922_000, 0.05, 875_900, 46_100),
            {875_900: 128_000, 900_000: 103_900},
        ),
        (
            (200_000, 64_000, None),
            (200_000, 0.05, 129_200, 6_800),
            {120_000: 64_000, 180_000: 13_200},
        ),
        ((200_000, 64_000, None), (8_000, 0.05, 7_600, 400), {7_600: 64_000}),
        ((100_000, 10_000, "100000"), (1_000_000, 0, 90_000, 0), {98_000: 2_000}),
        (
            (100_000, 10_000, 50_000),
            (1_000_000, 0, 40_000, 0),
            {40_000: 10_000, 48_000: 2_000},
        ),
        ((4_000, 4_000, None), (4_000, 0.05, 3_800, 200), {2_000: None}),
    ],
    ids=[
        "separate-limits",
        "shared-context",
        "operator-cap",
        "invalid-context",
        "smaller-context",
        "large-output",
    ],
)
def test_model_budget(
    model_map: ModelMap,
    llm: Mock,
    monkeypatch: pytest.MonkeyPatch,
    limits: tuple[object, object, object],
    input_config: tuple[int, float, int, int],
    outputs: dict[int, int | None],
) -> None:
    model_map["openai/model"] = {
        "max_input_tokens": limits[0],
        "max_output_tokens": limits[1],
        "max_context_tokens": limits[2],
    }
    input_cap, margin, expected_input, expected_safety = input_config
    llm.config.max_input_tokens = input_cap
    monkeypatch.setattr(
        "onyx.chat.token_budget.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", margin
    )
    budget = resolve_chat_token_budget(llm)
    assert (budget.input_tokens, budget.safety_tokens) == (
        expected_input,
        expected_safety,
    )
    for input_tokens, output_tokens in outputs.items():
        assert budget.output_allowance(input_tokens) == output_tokens


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        {"max_input_tokens": 128_000},
        {"max_output_tokens": 16_000},
        {"max_input_tokens": True, "max_output_tokens": 16_000},
        {"max_input_tokens": 128_000, "max_output_tokens": False},
        {"max_tokens": 128_000, "max_output_tokens": 16_000},
    ],
)
def test_missing_or_invalid_limits_keep_legacy_fallback(
    model_map: ModelMap,
    llm: Mock,
    metadata: dict[str, object] | None,
) -> None:
    if metadata is not None:
        model_map["openai/model"] = metadata
    llm.config.max_input_tokens = GEN_AI_MODEL_FALLBACK_MAX_TOKENS
    budget = resolve_chat_token_budget(llm)
    assert budget == ChatTokenBudget(30_400, None, None, 1_600)
    assert budget.output_allowance(1) is None


def test_deployment_alias(model_map: ModelMap, llm: Mock) -> None:
    llm.config.model_provider = "azure"
    llm.config.deployment_name = "alias"
    model_map["azure/alias"] = {
        "max_input_tokens": 128_000,
        "max_output_tokens": 16_000,
    }
    assert resolve_chat_token_budget(llm) == ChatTokenBudget(
        106_400, 16_000, 128_000, 5_600
    )


def test_provider_precedes_bare_model(
    model_map: ModelMap,
    llm: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.chat.token_budget.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", 0)
    llm.config.model_provider = "azure"
    llm.config.model_name = "openai/model"
    model_map.update(
        {
            "azure/model": {"max_input_tokens": 100_000, "max_output_tokens": 10_000},
            "model": {"max_input_tokens": 200_000, "max_output_tokens": 20_000},
        }
    )
    assert resolve_chat_token_budget(llm) == ChatTokenBudget(90_000, 10_000, 100_000, 0)


def test_partial_metadata_uses_complete_alias(
    model_map: ModelMap,
    llm: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.chat.token_budget.GEN_AI_INPUT_TOKEN_SAFETY_MARGIN", 0)
    llm.config.deployment_name = "alias"
    llm.config.max_input_tokens = 100_000
    model_map.update(
        {
            "openai/model": {"max_input_tokens": 100_000},
            "openai/alias": {"max_input_tokens": 200_000, "max_output_tokens": 20_000},
        }
    )
    assert resolve_chat_token_budget(llm) == ChatTokenBudget(
        100_000, 20_000, 200_000, 0
    )


@pytest.mark.parametrize("estimated_input_tokens", [95, 100, 200])
@pytest.mark.usefixtures("model_map")
def test_exhausted_context_keeps_legacy_fallback(
    estimated_input_tokens: int,
) -> None:
    assert (
        ChatTokenBudget(95, 10, 100, 5).output_allowance(estimated_input_tokens) is None
    )
