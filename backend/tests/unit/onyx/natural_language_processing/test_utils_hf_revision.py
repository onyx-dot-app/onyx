"""API-side HF tokenizers: registry models load at their pinned revision, other
names keep the plain call, and the default tokenizer stays the pre-granite model."""

from unittest.mock import patch

import pytest

from onyx.natural_language_processing import utils
from shared_configs.configs import DEFAULT_DOCUMENT_ENCODER_MODEL
from shared_configs.embedding_models import get_local_model_spec

_HF_TOKENIZER_CLASS = "onyx.natural_language_processing.utils.Tokenizer"
_NOMIC = "nomic-ai/nomic-embed-text-v1"


def _pinned_revision(model_name: str) -> str | None:
    spec = get_local_model_spec(model_name)
    assert spec is not None
    return spec.hf_revision


@pytest.mark.parametrize(
    ("model_name", "kwargs"),
    [
        (
            DEFAULT_DOCUMENT_ENCODER_MODEL,
            {"revision": _pinned_revision(DEFAULT_DOCUMENT_ENCODER_MODEL)},
        ),
        (_NOMIC, {}),
        # Only the exact registry name is pinned; a variant keeps the plain call.
        (DEFAULT_DOCUMENT_ENCODER_MODEL.upper(), {}),
    ],
    ids=["registry-model", "legacy-model", "registry-name-variant"],
)
def test_tokenizer_load_call(model_name: str, kwargs: dict[str, str | None]) -> None:
    with patch(_HF_TOKENIZER_CLASS) as mock_class:
        utils.HuggingFaceTokenizer(model_name)

    mock_class.from_pretrained.assert_called_once_with(model_name, **kwargs)


def test_no_model_name_uses_the_default_tokenizer_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not DOCUMENT_ENCODER_MODEL, which defaults to granite. The env semantics of
    DEFAULT_TOKENIZER_MODEL are pinned in test_embedding_model_registry_configs.py."""
    monkeypatch.setattr(utils, "_DEFAULT_TOKENIZER", None)
    monkeypatch.setattr(utils, "_TOKENIZER_CACHE", {})
    monkeypatch.setattr(utils, "DEFAULT_TOKENIZER_MODEL", _NOMIC)
    with patch(_HF_TOKENIZER_CLASS) as mock_class:
        result = utils.get_tokenizer(model_name=None, provider_type=None)

    mock_class.from_pretrained.assert_called_once_with(_NOMIC)
    assert isinstance(result, utils.HuggingFaceTokenizer)
