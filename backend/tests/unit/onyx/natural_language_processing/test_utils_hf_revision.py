"""API-side HF tokenizers: the default one keeps the pre-granite model (invariant
I8), registry models load at their pinned revision, and the API image bakes what
the default paths need."""

import os
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs import model_configs
from onyx.natural_language_processing import utils
from shared_configs.embedding_models import (
    DEFAULT_LOCAL_EMBEDDING_MODEL_NAME,
    EmbeddingModelSpec,
    get_local_model_spec,
    selectable_embedding_model_specs,
)

_HF_TOKENIZER_CLASS = "onyx.natural_language_processing.utils.Tokenizer"
_BACKEND_DOCKERFILE = Path(__file__).resolve().parents[4] / "Dockerfile"
_NOMIC = "nomic-ai/nomic-embed-text-v1"

_LOCAL_SELECTABLE_SPECS = [
    spec for spec in selectable_embedding_model_specs() if spec.provider_type is None
]


@pytest.fixture
def fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(utils, "_DEFAULT_TOKENIZER", None)
    monkeypatch.setattr(utils, "_TOKENIZER_CACHE", {})
    monkeypatch.setattr(utils, "DEFAULT_TOKENIZER_MODEL", _NOMIC)


@pytest.mark.parametrize(
    "spec", _LOCAL_SELECTABLE_SPECS, ids=lambda spec: spec.model_name
)
def test_registry_model_loads_at_pinned_revision(spec: EmbeddingModelSpec) -> None:
    with patch(_HF_TOKENIZER_CLASS) as mock_class:
        utils.HuggingFaceTokenizer(spec.model_name)

    mock_class.from_pretrained.assert_called_once_with(
        spec.model_name, revision=spec.hf_revision
    )


@pytest.mark.parametrize(
    "model_name",
    [
        _NOMIC,
        "intfloat/e5-base-v2",
        "my-org/custom-embedder",
        # Only the exact registry name is pinned; a variant keeps the plain call.
        DEFAULT_LOCAL_EMBEDDING_MODEL_NAME.upper(),
    ],
)
def test_other_model_keeps_the_plain_call(model_name: str) -> None:
    assert get_local_model_spec(model_name) is None

    with patch(_HF_TOKENIZER_CLASS) as mock_class:
        utils.HuggingFaceTokenizer(model_name)

    mock_class.from_pretrained.assert_called_once_with(model_name)


def test_default_model_comes_from_default_tokenizer_model() -> None:
    # Not DOCUMENT_ENCODER_MODEL, which now defaults to granite. The env
    # semantics of DEFAULT_TOKENIZER_MODEL are pinned in
    # tests/unit/onyx/configs/test_embedding_model_registry_configs.py.
    # Compare values: another test can load model_configs again, which binds
    # equal but new string objects.
    assert utils.DEFAULT_TOKENIZER_MODEL == model_configs.DEFAULT_TOKENIZER_MODEL
    if not os.environ.get("DOCUMENT_ENCODER_MODEL"):
        assert utils.DEFAULT_TOKENIZER_MODEL != model_configs.DOCUMENT_ENCODER_MODEL


@pytest.mark.usefixtures("fresh_cache")
def test_no_model_name_uses_the_default_model() -> None:
    with patch(_HF_TOKENIZER_CLASS) as mock_class:
        result = utils.get_tokenizer(model_name=None, provider_type=None)

    mock_class.from_pretrained.assert_called_once_with(_NOMIC)
    assert isinstance(result, utils.HuggingFaceTokenizer)


@pytest.mark.usefixtures("fresh_cache")
def test_failed_model_falls_back_to_the_default_model() -> None:
    default_encoder = MagicMock()

    def _from_pretrained(model_name: str, **_kwargs: str) -> MagicMock:
        if model_name == "voyageai/voyage-4-nano":
            raise OSError("offline")
        return default_encoder

    with patch(_HF_TOKENIZER_CLASS) as mock_class:
        mock_class.from_pretrained.side_effect = _from_pretrained
        result = utils.get_tokenizer(
            model_name="voyageai/voyage-4-nano", provider_type=None
        )

    assert isinstance(result, utils.HuggingFaceTokenizer)
    assert result.encoder is default_encoder
    assert [call.args[0] for call in mock_class.from_pretrained.call_args_list] == [
        "voyageai/voyage-4-nano",
        _NOMIC,
    ]


def _dockerfile_bakes() -> list[tuple[str, str | None]]:
    """(model_name, revision) of every Tokenizer.from_pretrained in the Dockerfile."""
    text = _BACKEND_DOCKERFILE.read_text()
    return [
        (match.group("name"), match.group("revision"))
        for match in re.finditer(
            r"Tokenizer\.from_pretrained\('(?P<name>[^']+)'"
            r"(?:,\s*revision='(?P<revision>[^']+)')?\)",
            text,
        )
    ]


def test_api_image_bakes_nomic() -> None:
    # The default tokenizer (chat token counting, fallback) must work offline.
    assert (_NOMIC, None) in _dockerfile_bakes()


def test_api_image_bakes_the_default_local_model_at_pinned_revision() -> None:
    spec = get_local_model_spec(DEFAULT_LOCAL_EMBEDDING_MODEL_NAME)
    assert spec is not None

    assert (spec.model_name, spec.hf_revision) in _dockerfile_bakes()


def test_every_baked_registry_model_uses_the_pinned_revision() -> None:
    for model_name, revision in _dockerfile_bakes():
        spec = get_local_model_spec(model_name)
        if spec is not None:
            assert revision == spec.hf_revision, model_name
