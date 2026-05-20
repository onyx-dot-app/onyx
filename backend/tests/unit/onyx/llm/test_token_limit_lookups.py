"""Tests for the token-limit lookup helpers in `onyx.llm.utils`:
`llm_max_input_tokens`, `get_llm_max_output_tokens`, and `get_max_input_tokens`."""

from unittest.mock import patch

from onyx.configs.model_configs import GEN_AI_MODEL_FALLBACK_MAX_TOKENS
from onyx.llm.utils import get_llm_max_output_tokens
from onyx.llm.utils import get_max_input_tokens
from onyx.llm.utils import llm_max_input_tokens


class TestLlmMaxInputTokens:
    def test_prefers_max_input_tokens(self) -> None:
        model_map = {"openai/gpt-4o": {"max_input_tokens": 128000, "max_tokens": 4096}}
        assert (
            llm_max_input_tokens(
                model_map=model_map,
                model_name="gpt-4o",
                model_provider="openai",
            )
            == 128000
        )

    def test_falls_back_to_max_tokens(self) -> None:
        model_map = {"openai/gpt-4o": {"max_tokens": 4096}}
        assert (
            llm_max_input_tokens(
                model_map=model_map,
                model_name="gpt-4o",
                model_provider="openai",
            )
            == 4096
        )

    def test_model_not_found_returns_fallback(self) -> None:
        assert (
            llm_max_input_tokens(
                model_map={},
                model_name="nonexistent",
                model_provider="openai",
            )
            == GEN_AI_MODEL_FALLBACK_MAX_TOKENS
        )

    def test_model_has_no_token_keys_returns_fallback(self) -> None:
        model_map = {"openai/gpt-4o": {"input_cost_per_token": 0.0001}}
        assert (
            llm_max_input_tokens(
                model_map=model_map,
                model_name="gpt-4o",
                model_provider="openai",
            )
            == GEN_AI_MODEL_FALLBACK_MAX_TOKENS
        )

    def test_none_max_input_tokens_falls_through(self) -> None:
        # Regression: litellm 1.83.0 ships entries like ollama_chat/gpt-oss:20b-cloud
        # with `max_input_tokens: None` — previously returned None and crashed callers.
        model_map = {
            "ollama_chat/gpt-oss:20b-cloud": {
                "max_input_tokens": None,
                "max_tokens": 131072,
            }
        }
        assert (
            llm_max_input_tokens(
                model_map=model_map,
                model_name="gpt-oss:20b-cloud",
                model_provider="ollama_chat",
            )
            == 131072
        )

    def test_all_none_falls_back_to_default(self) -> None:
        model_map = {
            "ollama_chat/gpt-oss:20b-cloud": {
                "max_input_tokens": None,
                "max_tokens": None,
            }
        }
        assert (
            llm_max_input_tokens(
                model_map=model_map,
                model_name="gpt-oss:20b-cloud",
                model_provider="ollama_chat",
            )
            == GEN_AI_MODEL_FALLBACK_MAX_TOKENS
        )

    def test_override_env_var_wins(self) -> None:
        model_map = {"openai/gpt-4o": {"max_input_tokens": 128000}}
        with patch("onyx.llm.utils.GEN_AI_MAX_TOKENS", 5000):
            assert (
                llm_max_input_tokens(
                    model_map=model_map,
                    model_name="gpt-4o",
                    model_provider="openai",
                )
                == 5000
            )


class TestGetLlmMaxOutputTokens:
    def test_prefers_max_output_tokens(self) -> None:
        model_map = {
            "openai/gpt-4o": {"max_output_tokens": 16384, "max_tokens": 128000}
        }
        assert (
            get_llm_max_output_tokens(
                model_map=model_map,
                model_name="gpt-4o",
                model_provider="openai",
            )
            == 16384
        )

    def test_falls_back_to_ten_percent_of_max_tokens(self) -> None:
        model_map = {"openai/gpt-4o": {"max_tokens": 100000}}
        assert (
            get_llm_max_output_tokens(
                model_map=model_map,
                model_name="gpt-4o",
                model_provider="openai",
            )
            == 10000
        )

    def test_lookup_without_provider_prefix(self) -> None:
        model_map = {"gpt-4o": {"max_output_tokens": 4096}}
        assert (
            get_llm_max_output_tokens(
                model_map=model_map,
                model_name="gpt-4o",
                model_provider="openai",
            )
            == 4096
        )

    def test_model_not_found_returns_fallback(self) -> None:
        assert get_llm_max_output_tokens(
            model_map={},
            model_name="nonexistent",
            model_provider="openai",
        ) == int(GEN_AI_MODEL_FALLBACK_MAX_TOKENS)

    def test_none_max_output_tokens_falls_through(self) -> None:
        # Regression — same None-in-model_cost shape as litellm 1.83.0 produces.
        model_map = {
            "ollama_chat/gpt-oss:20b-cloud": {
                "max_output_tokens": None,
                "max_tokens": 131072,
            }
        }
        assert get_llm_max_output_tokens(
            model_map=model_map,
            model_name="gpt-oss:20b-cloud",
            model_provider="ollama_chat",
        ) == int(131072 * 0.1)

    def test_all_none_falls_back_to_default(self) -> None:
        model_map = {
            "ollama_chat/gpt-oss:20b-cloud": {
                "max_output_tokens": None,
                "max_tokens": None,
            }
        }
        assert get_llm_max_output_tokens(
            model_map=model_map,
            model_name="gpt-oss:20b-cloud",
            model_provider="ollama_chat",
        ) == int(GEN_AI_MODEL_FALLBACK_MAX_TOKENS)


class TestGetMaxInputTokens:
    def test_subtracts_reserved_output_tokens(self) -> None:
        model_map = {"openai/gpt-4o": {"max_input_tokens": 128000}}
        with patch("onyx.llm.utils.get_model_map", return_value=model_map):
            assert (
                get_max_input_tokens(
                    model_name="gpt-4o",
                    model_provider="openai",
                    output_tokens=1024,
                )
                == 128000 - 1024
            )

    def test_non_positive_budget_falls_back(self) -> None:
        model_map = {"tiny/model": {"max_input_tokens": 100}}
        with patch("onyx.llm.utils.get_model_map", return_value=model_map):
            assert (
                get_max_input_tokens(
                    model_name="model",
                    model_provider="tiny",
                    output_tokens=100,
                )
                == GEN_AI_MODEL_FALLBACK_MAX_TOKENS
            )

    def test_does_not_raise_when_litellm_returns_none_values(self) -> None:
        # This is the exact path that 500'd the nightly provider chat test
        # for ollama_chat/gpt-oss:20b-cloud on litellm 1.83.0.
        model_map = {
            "ollama_chat/gpt-oss:20b-cloud": {
                "max_input_tokens": None,
                "max_tokens": None,
            }
        }
        with patch("onyx.llm.utils.get_model_map", return_value=model_map):
            result = get_max_input_tokens(
                model_name="gpt-oss:20b-cloud",
                model_provider="ollama_chat",
            )
        assert isinstance(result, int)
        assert result > 0
