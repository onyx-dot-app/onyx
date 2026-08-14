"""Tests for the token-limit lookup helpers in `onyx.llm.model_capabilities`:
`llm_max_input_tokens`, `get_llm_max_output_tokens`, and `get_max_input_tokens`."""

from unittest.mock import patch

from onyx.configs.model_configs import GEN_AI_MODEL_FALLBACK_MAX_TOKENS
from onyx.llm.model_capabilities import (
    get_llm_max_output_tokens,
    get_max_input_tokens,
    llm_max_input_tokens,
    resolve_max_output_tokens,
)


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
        with patch("onyx.llm.model_capabilities.GEN_AI_MAX_TOKENS", 5000):
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

    def test_lookup_strips_proxy_provider_prefix(self) -> None:
        model_map = {"azure/gpt-5": {"max_output_tokens": 128000}}
        assert (
            get_llm_max_output_tokens(
                model_map=model_map,
                model_name="openai/gpt-5",
                model_provider="azure",
            )
            == 128000
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
        with patch("onyx.llm.model_capabilities.get_model_map", return_value=model_map):
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
        with patch("onyx.llm.model_capabilities.get_model_map", return_value=model_map):
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
        with patch("onyx.llm.model_capabilities.get_model_map", return_value=model_map):
            result = get_max_input_tokens(
                model_name="gpt-oss:20b-cloud",
                model_provider="ollama_chat",
            )
        assert isinstance(result, int)
        assert result > 0


class TestResolveMaxOutputTokens:
    """`resolve_max_output_tokens` must never guess a ceiling: it returns the
    model's real limit or None, so callers don't send a value the provider
    rejects."""

    def test_resolves_known_model(self) -> None:
        model_map = {"anthropic/claude-sonnet-5": {"max_output_tokens": 128000}}
        with patch("onyx.llm.model_capabilities.get_model_map", return_value=model_map):
            assert resolve_max_output_tokens("claude-sonnet-5", "anthropic") == 128000

    def test_returns_none_for_unknown_model(self) -> None:
        with patch("onyx.llm.model_capabilities.get_model_map", return_value={}):
            assert resolve_max_output_tokens("some-local-model", "ollama") is None

    def test_returns_none_when_entry_lacks_output_tokens(self) -> None:
        model_map = {"ollama/llama3": {"max_input_tokens": 8192}}
        with patch("onyx.llm.model_capabilities.get_model_map", return_value=model_map):
            assert resolve_max_output_tokens("llama3", "ollama") is None

    def test_strips_bedrock_inference_profile_prefix(self) -> None:
        # GovCloud ids are absent from LiteLLM's map; the base id is present.
        model_map = {"anthropic.claude-sonnet-5": {"max_output_tokens": 128000}}
        with patch("onyx.llm.model_capabilities.get_model_map", return_value=model_map):
            assert (
                resolve_max_output_tokens("us-gov.anthropic.claude-sonnet-5", "bedrock")
                == 128000
            )

    def test_prefix_strip_requires_a_vendor_namespace(self) -> None:
        # A self-hosted model merely starting with "us." must not inherit an
        # unrelated model's ceiling.
        model_map = {"foo": {"max_output_tokens": 128000}}
        with patch("onyx.llm.model_capabilities.get_model_map", return_value=model_map):
            assert resolve_max_output_tokens("us.foo", "ollama") is None

    def test_prefix_strip_still_returns_none_when_base_unknown(self) -> None:
        with patch("onyx.llm.model_capabilities.get_model_map", return_value={}):
            assert (
                resolve_max_output_tokens(
                    "us-gov.anthropic.claude-sonnet-4-5", "bedrock"
                )
                is None
            )
