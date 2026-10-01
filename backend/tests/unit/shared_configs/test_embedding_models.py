"""Integrity of the shared embedding-model registry and its lookup helpers."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from shared_configs.configs import DEFAULT_DOCUMENT_ENCODER_MODEL
from shared_configs.embedding_models import (
    DEFAULT_LOCAL_EMBEDDING_MODEL_NAME,
    EMBEDDING_MODEL_SPECS,
    EmbeddingModelSpec,
    EmbeddingModelStatus,
    LocalModelLoader,
    bundled_local_model_names,
    find_embedding_model_spec,
    get_local_model_spec,
    selectable_embedding_model_specs,
)
from shared_configs.enums import EmbeddingProvider
from shared_configs.utils import clean_model_name

_BACKEND_DIR = Path(__file__).resolve().parents[3]

GRANITE = "ibm-granite/granite-embedding-97m-multilingual-r2"
VOYAGE_NANO = "voyageai/voyage-4-nano"
NEMOTRON = "nvidia/Nemotron-3-Embed-1B-BF16"

# (provider_type, model_name, dim, normalize, query_prefix, passage_prefix)
_EXPECTED_SELECTABLE: list[
    tuple[EmbeddingProvider | None, str, int, bool, str, str]
] = [
    (None, GRANITE, 384, True, "", ""),
    (
        None,
        VOYAGE_NANO,
        2048,
        True,
        "Represent the query for retrieving supporting documents: ",
        "Represent the document for retrieval: ",
    ),
    (None, NEMOTRON, 2048, True, "query: ", "passage: "),
    (EmbeddingProvider.COHERE, "embed-v5.0-pro", 2048, False, "", ""),
    (EmbeddingProvider.COHERE, "embed-v5.0-fast", 2048, False, "", ""),
    (EmbeddingProvider.GOOGLE, "gemini-embedding-2", 3072, False, "", ""),
    (EmbeddingProvider.OPENAI, "text-embedding-3-large", 3072, False, "", ""),
    (EmbeddingProvider.OPENAI, "text-embedding-3-small", 1536, False, "", ""),
]

_EXPECTED_LEGACY: list[tuple[EmbeddingProvider | None, str]] = [
    (None, "nomic-ai/nomic-embed-text-v1"),
    (None, "intfloat/e5-base-v2"),
    (None, "intfloat/e5-small-v2"),
    (None, "intfloat/multilingual-e5-base"),
    (None, "intfloat/multilingual-e5-small"),
    (None, "thenlper/gte-small"),
    (EmbeddingProvider.COHERE, "embed-english-v3.0"),
    (EmbeddingProvider.COHERE, "embed-english-light-v3.0"),
    (EmbeddingProvider.COHERE, "embed-v4.0"),
    (EmbeddingProvider.GOOGLE, "gemini-embedding-001"),
    (EmbeddingProvider.GOOGLE, "text-embedding-005"),
    (EmbeddingProvider.GOOGLE, "gemini-embedding-2-preview"),
    (EmbeddingProvider.GOOGLE, "text-embedding-004"),
    (EmbeddingProvider.GOOGLE, "textembedding-gecko@003"),
    (EmbeddingProvider.VOYAGE, "voyage-large-2-instruct"),
    (EmbeddingProvider.VOYAGE, "voyage-light-2-instruct"),
]


def _selectable_self_hosted() -> list[EmbeddingModelSpec]:
    return [
        spec
        for spec in selectable_embedding_model_specs()
        if spec.provider_type is None
    ]


def test_match_keys_are_unique() -> None:
    keys = [
        (spec.provider_type, clean_model_name(spec.model_name))
        for spec in EMBEDDING_MODEL_SPECS
    ]
    assert len(keys) == len(set(keys))


def test_registry_is_exactly_the_selectable_and_legacy_models() -> None:
    selectable = {(p, name) for p, name, *_ in _EXPECTED_SELECTABLE}
    legacy = set(_EXPECTED_LEGACY)
    actual = {(spec.provider_type, spec.model_name) for spec in EMBEDDING_MODEL_SPECS}
    assert actual == selectable | legacy
    for provider_type, model_name in legacy:
        spec = find_embedding_model_spec(provider_type, model_name)
        assert spec is not None
        assert spec.status == EmbeddingModelStatus.LEGACY


@pytest.mark.parametrize(
    "provider_type,model_name,dim,normalize,query_prefix,passage_prefix",
    _EXPECTED_SELECTABLE,
    ids=[name for _, name, *_ in _EXPECTED_SELECTABLE],
)
def test_selectable_model_values(
    provider_type: EmbeddingProvider | None,
    model_name: str,
    dim: int,
    normalize: bool,
    query_prefix: str,
    passage_prefix: str,
) -> None:
    spec = find_embedding_model_spec(provider_type, model_name)
    assert spec is not None
    assert spec.model_name == model_name
    assert spec.status == EmbeddingModelStatus.SELECTABLE
    assert spec.model_dim == dim
    assert spec.normalize is normalize
    assert spec.query_prefix == query_prefix
    assert spec.passage_prefix == passage_prefix


def test_selectable_specs_helper_returns_the_eight_models_in_order() -> None:
    names = [spec.model_name for spec in selectable_embedding_model_specs()]
    assert names == [name for _, name, *_ in _EXPECTED_SELECTABLE]


def test_only_selectable_self_hosted_models_pin_a_revision() -> None:
    pinned = {spec.model_name for spec in EMBEDDING_MODEL_SPECS if spec.hf_revision}
    assert pinned == {GRANITE, VOYAGE_NANO, NEMOTRON}
    for spec in _selectable_self_hosted():
        assert spec.hf_revision is not None
        assert re.fullmatch(r"[0-9a-f]{40}", spec.hf_revision)


def test_exactly_one_bundled_model_and_it_is_the_default() -> None:
    assert DEFAULT_LOCAL_EMBEDDING_MODEL_NAME == DEFAULT_DOCUMENT_ENCODER_MODEL
    assert bundled_local_model_names() == frozenset({DEFAULT_DOCUMENT_ENCODER_MODEL})
    bundled = [spec for spec in EMBEDDING_MODEL_SPECS if spec.bundled_in_image]
    assert len(bundled) == 1
    assert bundled[0].provider_type is None
    assert bundled[0].status == EmbeddingModelStatus.SELECTABLE


def test_loader_gpu_and_reduced_dimension_flags() -> None:
    projection = {
        spec.model_name
        for spec in EMBEDDING_MODEL_SPECS
        if spec.loader == LocalModelLoader.VOYAGE_BIDIRECTIONAL_PROJECTION
    }
    assert projection == {VOYAGE_NANO}
    assert {s.model_name for s in EMBEDDING_MODEL_SPECS if s.gpu_recommended} == {
        NEMOTRON
    }
    assert {
        s.model_name for s in EMBEDDING_MODEL_SPECS if s.supports_reduced_dimension
    } == {"text-embedding-3-large", "text-embedding-3-small", "gemini-embedding-2"}


def test_cloud_models_have_no_prefixes_or_local_loader_settings() -> None:
    """The cloud path refuses any prefix, and loader settings are local-only."""
    for spec in EMBEDDING_MODEL_SPECS:
        if spec.provider_type is None:
            continue
        assert spec.query_prefix == ""
        assert spec.passage_prefix == ""
        assert spec.normalize is False
        assert spec.hf_revision is None
        assert spec.loader == LocalModelLoader.STANDARD
        assert spec.bundled_in_image is False


@pytest.mark.parametrize(
    "provider_type,query_name,expected_name",
    [
        (None, GRANITE, GRANITE),
        (None, "IBM-Granite/Granite-Embedding-97M-Multilingual-R2", GRANITE),
        (None, "  ibm-granite/granite-embedding-97m-multilingual-r2\n", GRANITE),
        (None, "ibm_granite_granite_embedding_97m_multilingual_r2", GRANITE),
        (None, "NVIDIA/nemotron-3-embed-1b-bf16", NEMOTRON),
        (None, "IntFloat/E5-Base-V2", "intfloat/e5-base-v2"),
        (EmbeddingProvider.COHERE, "EMBED-V5.0-PRO", "embed-v5.0-pro"),
        (EmbeddingProvider.COHERE, " embed_v5_0_fast ", "embed-v5.0-fast"),
        (EmbeddingProvider.COHERE, "embed-english-v3.0", "embed-english-v3.0"),
        (EmbeddingProvider.GOOGLE, "Gemini-Embedding-2", "gemini-embedding-2"),
        (
            EmbeddingProvider.GOOGLE,
            "textembedding-gecko@003",
            "textembedding-gecko@003",
        ),
    ],
)
def test_find_spec_folds_case_punctuation_and_whitespace(
    provider_type: EmbeddingProvider | None, query_name: str, expected_name: str
) -> None:
    spec = find_embedding_model_spec(provider_type, query_name)
    assert spec is not None
    assert spec.model_name == expected_name
    assert spec.provider_type == provider_type


@pytest.mark.parametrize(
    "provider_type,query_name",
    [
        # Right name, wrong provider.
        (None, "embed-v5.0-pro"),
        (EmbeddingProvider.OPENAI, GRANITE),
        (EmbeddingProvider.VOYAGE, VOYAGE_NANO),
        # Free-form providers are never in the registry.
        (EmbeddingProvider.LITELLM, "text-embedding-3-large"),
        (EmbeddingProvider.AZURE, "text-embedding-3-large"),
        # Unknown names.
        (None, "my-org/custom-model"),
        (None, "ibm-granite/granite-embedding-97m-multilingual"),
        (EmbeddingProvider.COHERE, "embed-v5.0"),
    ],
)
def test_find_spec_returns_none_for_unknown_keys(
    provider_type: EmbeddingProvider | None, query_name: str
) -> None:
    assert find_embedding_model_spec(provider_type, query_name) is None


def test_find_spec_accepts_a_plain_string_provider() -> None:
    """Callers may hold the raw DB/JSON value instead of the enum member."""
    spec = find_embedding_model_spec(EmbeddingProvider("cohere"), "embed-v5.0-pro")
    assert spec is not None
    raw_value_spec = find_embedding_model_spec(
        "cohere",  # ty: ignore[invalid-argument-type]
        "embed-v5.0-pro",
    )
    assert raw_value_spec is spec


@pytest.mark.parametrize("model_name", [GRANITE, VOYAGE_NANO, NEMOTRON])
def test_get_local_model_spec_matches_exact_selectable_names(model_name: str) -> None:
    spec = get_local_model_spec(model_name)
    assert spec is not None
    assert spec.model_name == model_name
    assert spec.hf_revision is not None


@pytest.mark.parametrize(
    "model_name",
    [
        # Case and whitespace variants must keep the legacy load path.
        "IBM-Granite/Granite-Embedding-97M-Multilingual-R2",
        "nvidia/nemotron-3-embed-1b-bf16",
        f" {VOYAGE_NANO}",
        # Legacy and custom self-hosted models.
        "nomic-ai/nomic-embed-text-v1",
        "intfloat/e5-base-v2",
        "thenlper/gte-small",
        "my-org/custom-model",
        # Cloud model names.
        "embed-v5.0-pro",
        "text-embedding-3-large",
    ],
)
def test_get_local_model_spec_rejects_everything_else(model_name: str) -> None:
    assert get_local_model_spec(model_name) is None


@pytest.mark.parametrize(
    "model_name,expected",
    [
        ("nomic-ai/nomic-embed-text-v1", "nomic_ai_nomic_embed_text_v1"),
        ("embed-v5.0-pro", "embed_v5_0_pro"),
        (GRANITE, "ibm_granite_granite_embedding_97m_multilingual_r2"),
        (NEMOTRON, "nvidia_nemotron_3_embed_1b_bf16"),
        ("textembedding-gecko@003", "textembedding_gecko@003"),
        ("Qwen3-VL-Embedding-8B", "qwen3_vl_embedding_8b"),
        (" a.b ", " a_b "),
    ],
)
def test_clean_model_name_output_is_pinned(model_name: str, expected: str) -> None:
    """Index names derive from this output, so it must never change."""
    assert clean_model_name(model_name) == expected


def test_registry_imports_no_onyx_or_ml_packages() -> None:
    """The model-server image has no onyx package and the API image has no torch."""
    code = (
        "import sys\n"
        "import shared_configs.embedding_models\n"
        "banned = {'onyx', 'ee', 'model_server', 'torch', 'transformers',"
        " 'sentence_transformers'}\n"
        "print(sorted(m for m in sys.modules if m.split('.')[0] in banned))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_BACKEND_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "[]"
