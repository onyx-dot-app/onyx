from unittest.mock import patch

import pytest

from onyx.natural_language_processing import utils
from shared_configs.enums import EmbeddingProvider

_TIKTOKEN = "onyx.natural_language_processing.utils.TiktokenTokenizer"
_HF = "onyx.natural_language_processing.utils.HuggingFaceTokenizer"


@pytest.fixture(autouse=True)
def _clear_tokenizer_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(utils, "_TOKENIZER_CACHE", {})
    monkeypatch.setattr(utils, "_MODEL_TOKENIZER_CACHE", {})
    monkeypatch.setattr(utils, "_DEFAULT_TOKENIZER", None)


def test_generation_provider_resolves_the_model_tokenizer() -> None:
    sentinel = object()

    with patch(_TIKTOKEN, return_value=sentinel) as mock_tiktoken:
        result = utils.get_tokenizer(
            model_name="qwen3-8b", provider_type="litellm_proxy"
        )

    mock_tiktoken.assert_called_once_with("qwen3-8b")
    assert result is sentinel


def test_generation_provider_falls_back_to_huggingface() -> None:
    sentinel = object()

    with (
        patch(_TIKTOKEN, side_effect=ValueError("unknown model")),
        patch(_HF, return_value=sentinel) as mock_hf,
    ):
        result = utils.get_tokenizer(
            model_name="org/model", provider_type="litellm_proxy"
        )

    mock_hf.assert_called_once_with("org/model")
    assert result is sentinel


def test_generation_provider_prefers_the_deployment_name() -> None:
    sentinel = object()

    with patch(_TIKTOKEN, return_value=sentinel) as mock_tiktoken:
        result = utils.get_tokenizer(
            model_name="gpt-4o",
            provider_type="litellm_proxy",
            deployment_name="served-model",
        )

    mock_tiktoken.assert_called_once_with("served-model")
    assert result is sentinel


def test_generation_provider_caches_failed_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default = object()
    monkeypatch.setattr(utils, "_get_default_tokenizer", lambda: default)

    with (
        patch(_TIKTOKEN, side_effect=ValueError("unknown model")),
        patch(_HF, side_effect=ValueError("unknown model")) as mock_hf,
    ):
        first = utils.get_tokenizer(
            model_name="unknown", provider_type="litellm_proxy"
        )
        second = utils.get_tokenizer(
            model_name="unknown", provider_type="litellm_proxy"
        )

    assert first is default
    assert second is default
    assert mock_hf.call_count == 1


def test_embedding_provider_still_uses_the_provider_cache() -> None:
    sentinel = object()

    with patch(_TIKTOKEN, return_value=sentinel):
        result = utils.get_tokenizer(
            model_name="text-embedding-3-small", provider_type="openai"
        )

    assert result is sentinel
    assert (
        utils._TOKENIZER_CACHE[
            (EmbeddingProvider.OPENAI, "text-embedding-3-small")
        ]
        is sentinel
    )


def test_generation_provider_without_a_model_keeps_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default = object()
    monkeypatch.setattr(utils, "_get_default_tokenizer", lambda: default)

    assert utils.get_tokenizer(model_name=None, provider_type="litellm_proxy") is default


def test_generation_provider_with_unresolvable_model_keeps_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default = object()
    monkeypatch.setattr(utils, "_get_default_tokenizer", lambda: default)

    with (
        patch(_TIKTOKEN, side_effect=ValueError("unknown model")),
        patch(_HF, side_effect=ValueError("unknown model")),
    ):
        assert utils.get_tokenizer(model_name="unknown", provider_type="litellm_proxy") is default
