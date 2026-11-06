from unittest.mock import patch

import pytest

from onyx.natural_language_processing import utils

_TIKTOKEN = "onyx.natural_language_processing.utils.TiktokenTokenizer"
_HF = "onyx.natural_language_processing.utils.HuggingFaceTokenizer"


@pytest.fixture(autouse=True)
def _clear_tokenizer_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(utils, "_TOKENIZER_CACHE", {})
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
