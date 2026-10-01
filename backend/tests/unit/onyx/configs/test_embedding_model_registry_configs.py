"""The shared embedding registry vs. the onyx config modules that depend on it."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.configs.embedding_configs import SUPPORTED_EMBEDDING_MODELS
from onyx.context.search.models import SearchSettingsCreationRequest
from onyx.natural_language_processing import search_nlp_models
from onyx.server.manage.search_settings import _compute_index_name
from shared_configs import utils as shared_utils
from shared_configs.embedding_models import (
    EmbeddingModelSpec,
    selectable_embedding_model_specs,
)

_MODEL_ENV_VARS = (
    "DOCUMENT_ENCODER_MODEL",
    "DOC_EMBEDDING_DIM",
    "NORMALIZE_EMBEDDINGS",
    "ASYM_QUERY_PREFIX",
    "ASYM_PASSAGE_PREFIX",
)

# Every index name registered before the new models. Multi-tenant schema setup
# depends on them, so they must never be removed.
_PRE_EXISTING_INDEX_NAMES = {
    "danswer_chunk_cohere_embed_english_v3_0",
    "danswer_chunk_embed_english_v3_0",
    "danswer_chunk_cohere_embed_english_light_v3_0",
    "danswer_chunk_embed_english_light_v3_0",
    "danswer_chunk_cohere_embed_v4_0",
    "danswer_chunk_openai_text_embedding_3_large",
    "danswer_chunk_text_embedding_3_large",
    "danswer_chunk_openai_text_embedding_3_small",
    "danswer_chunk_text_embedding_3_small",
    "danswer_chunk_gemini_embedding_001",
    "danswer_chunk_text_embedding_005",
    "danswer_chunk_gemini_embedding_2_preview",
    "danswer_chunk_gemini_embedding_2",
    "danswer_chunk_voyage_large_2_instruct",
    "danswer_chunk_large_2_instruct",
    "danswer_chunk_voyage_light_2_instruct",
    "danswer_chunk_light_2_instruct",
    "danswer_chunk_nomic_ai_nomic_embed_text_v1",
    "danswer_chunk_nomic_embed_text_v1",
    "danswer_chunk_intfloat_e5_base_v2",
    "danswer_chunk_intfloat_e5_small_v2",
    "danswer_chunk_intfloat_multilingual_e5_base",
    "danswer_chunk_intfloat_multilingual_e5_small",
}


def _creation_request(spec: EmbeddingModelSpec) -> SearchSettingsCreationRequest:
    return SearchSettingsCreationRequest(
        model_name=spec.model_name,
        model_dim=spec.model_dim,
        normalize=spec.normalize,
        query_prefix=spec.query_prefix,
        passage_prefix=spec.passage_prefix,
        provider_type=spec.provider_type,
        index_name=None,
        multipass_indexing=False,
        enable_contextual_rag=False,
    )


@pytest.mark.parametrize(
    "spec",
    selectable_embedding_model_specs(),
    ids=lambda spec: spec.model_name,
)
def test_selectable_model_base_index_name_is_supported(
    spec: EmbeddingModelSpec,
) -> None:
    present = MagicMock()
    present.model_name = "some-org/some-other-present-model"
    present.index_name = "danswer_chunk_some_org_some_other_present_model"

    index_name = _compute_index_name(_creation_request(spec), present)

    matches = [m for m in SUPPORTED_EMBEDDING_MODELS if m.index_name == index_name]
    assert len(matches) == 1
    assert matches[0].dim == spec.model_dim


@pytest.mark.parametrize(
    "name,dim,index_name",
    [
        ("cohere/embed-v5.0-pro", 2048, "danswer_chunk_embed_v5_0_pro"),
        ("cohere/embed-v5.0-fast", 2048, "danswer_chunk_embed_v5_0_fast"),
        (
            "ibm-granite/granite-embedding-97m-multilingual-r2",
            384,
            "danswer_chunk_ibm_granite_granite_embedding_97m_multilingual_r2",
        ),
        ("voyageai/voyage-4-nano", 2048, "danswer_chunk_voyageai_voyage_4_nano"),
        (
            "nvidia/Nemotron-3-Embed-1B-BF16",
            2048,
            "danswer_chunk_nvidia_nemotron_3_embed_1b_bf16",
        ),
    ],
)
def test_new_supported_embedding_models(name: str, dim: int, index_name: str) -> None:
    matches = [m for m in SUPPORTED_EMBEDDING_MODELS if m.name == name]
    assert len(matches) == 1
    assert matches[0].dim == dim
    assert matches[0].index_name == index_name


def test_no_pre_existing_index_name_was_removed() -> None:
    index_names = {m.index_name for m in SUPPORTED_EMBEDDING_MODELS}
    assert _PRE_EXISTING_INDEX_NAMES <= index_names


def test_clean_model_name_is_re_exported_from_search_nlp_models() -> None:
    """alembic dbaa756c2ccf imports it from search_nlp_models."""
    assert search_nlp_models.clean_model_name is shared_utils.clean_model_name


_BACKEND_DIR = Path(__file__).resolve().parents[4]


def _run_python(code: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run code in a new interpreter with exactly the given model env vars.

    model_configs reads the env at import. A reload in this process would rebind
    its globals for every later test, so each case gets its own process."""
    child_env = {k: v for k, v in os.environ.items() if k not in _MODEL_ENV_VARS}
    child_env.update(env)
    child_env["PYTHONPATH"] = str(_BACKEND_DIR)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_BACKEND_DIR,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result


def _last_json_line(result: subprocess.CompletedProcess[str]) -> Any:
    return json.loads(result.stdout.strip().splitlines()[-1])


# Prints the model settings that model_configs derives from the env.
_CONFIG_PROBE = """
import json
import onyx.configs.model_configs as m
print(json.dumps([
    m.DOCUMENT_ENCODER_MODEL, m.DOC_EMBEDDING_DIM, m.NORMALIZE_EMBEDDINGS,
    m.ASYM_QUERY_PREFIX, m.ASYM_PASSAGE_PREFIX, m.DEFAULT_TOKENIZER_MODEL,
]))
"""

NOMIC = "nomic-ai/nomic-embed-text-v1"
GRANITE = "ibm-granite/granite-embedding-97m-multilingual-r2"
_GRANITE_VALUES = [GRANITE, 384, True, "", "", NOMIC]
_ALL_MODEL_SETTING_VARS = [
    "DOC_EMBEDDING_DIM",
    "NORMALIZE_EMBEDDINGS",
    "ASYM_QUERY_PREFIX",
    "ASYM_PASSAGE_PREFIX",
]


@pytest.mark.parametrize(
    "env,expected,ignored_vars",
    [
        # Fresh default: granite, from its registry spec.
        ({}, _GRANITE_VALUES, []),
        ({"DOCUMENT_ENCODER_MODEL": ""}, _GRANITE_VALUES, []),
        # nomic via env: exactly the pre-granite values.
        (
            {"DOCUMENT_ENCODER_MODEL": NOMIC},
            [NOMIC, 768, True, "search_query: ", "search_document: ", NOMIC],
            [],
        ),
        # An env prefix explicitly set to "" stays "".
        (
            {
                "DOCUMENT_ENCODER_MODEL": NOMIC,
                "ASYM_QUERY_PREFIX": "",
                "ASYM_PASSAGE_PREFIX": "",
            },
            [NOMIC, 768, True, "", "", NOMIC],
            [],
        ),
        # Other registry models take their spec values.
        (
            {"DOCUMENT_ENCODER_MODEL": "voyageai/voyage-4-nano"},
            [
                "voyageai/voyage-4-nano",
                2048,
                True,
                "Represent the query for retrieving supporting documents: ",
                "Represent the document for retrieval: ",
                "voyageai/voyage-4-nano",
            ],
            [],
        ),
        (
            {"DOCUMENT_ENCODER_MODEL": "thenlper/gte-small"},
            ["thenlper/gte-small", 384, False, "", "", "thenlper/gte-small"],
            [],
        ),
        # Models not in the registry keep the old literal defaults.
        (
            {"DOCUMENT_ENCODER_MODEL": "my-org/custom-model"},
            [
                "my-org/custom-model",
                768,
                True,
                "search_query: ",
                "search_document: ",
                "my-org/custom-model",
            ],
            [],
        ),
        # With DOCUMENT_ENCODER_MODEL set, env vars win over the spec.
        (
            {
                "DOCUMENT_ENCODER_MODEL": NOMIC,
                "DOC_EMBEDDING_DIM": "1024",
                "NORMALIZE_EMBEDDINGS": "false",
                "ASYM_QUERY_PREFIX": "q: ",
                "ASYM_PASSAGE_PREFIX": "p: ",
            },
            [NOMIC, 1024, False, "q: ", "p: ", NOMIC],
            [],
        ),
        (
            {
                "DOCUMENT_ENCODER_MODEL": "thenlper/gte-small",
                "NORMALIZE_EMBEDDINGS": "TRUE",
            },
            ["thenlper/gte-small", 384, True, "", "", "thenlper/gte-small"],
            [],
        ),
        # Without DOCUMENT_ENCODER_MODEL, values that differ from the default
        # model's spec are ignored, e.g. an old env file written for nomic.
        (
            {
                "DOC_EMBEDDING_DIM": "768",
                "ASYM_QUERY_PREFIX": "search_query: ",
                "ASYM_PASSAGE_PREFIX": "search_document: ",
            },
            _GRANITE_VALUES,
            ["DOC_EMBEDDING_DIM", "ASYM_QUERY_PREFIX", "ASYM_PASSAGE_PREFIX"],
        ),
        (
            {
                "DOC_EMBEDDING_DIM": "1024",
                "NORMALIZE_EMBEDDINGS": "false",
                "ASYM_QUERY_PREFIX": "q: ",
                "ASYM_PASSAGE_PREFIX": "p: ",
            },
            _GRANITE_VALUES,
            _ALL_MODEL_SETTING_VARS,
        ),
        # Values equal to the spec (e.g. the Helm chart's empty prefixes) and
        # empty numeric/bool vars change nothing, so nothing is ignored.
        (
            {
                "DOC_EMBEDDING_DIM": "384",
                "NORMALIZE_EMBEDDINGS": "true",
                "ASYM_QUERY_PREFIX": "",
                "ASYM_PASSAGE_PREFIX": "",
            },
            _GRANITE_VALUES,
            [],
        ),
        (
            {"DOC_EMBEDDING_DIM": "", "NORMALIZE_EMBEDDINGS": ""},
            _GRANITE_VALUES,
            [],
        ),
    ],
)
def test_model_configs_derive_defaults_from_the_registry(
    env: dict[str, str], expected: list[object], ignored_vars: list[str]
) -> None:
    result = _run_python(_CONFIG_PROBE, env)

    assert _last_json_line(result) == expected
    if ignored_vars:
        assert f"Ignoring {', '.join(ignored_vars)}:" in result.stderr
    else:
        assert "Ignoring" not in result.stderr


# Loads alembic dbaa756c2ccf from its file and prints the rows it seeds.
_SEED_PROBE = """
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "seed", "alembic/versions/dbaa756c2ccf_embedding_models.py"
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
rows = [["PRESENT", migration._get_old_default_embedding_model()]]
if not migration.user_has_overridden_embedding_model():
    rows.append(["FUTURE", migration._get_new_default_embedding_model()])
print(json.dumps([
    [status, s.model_name, s.model_dim, s.normalize, s.query_prefix,
     s.passage_prefix, s.index_name]
    for status, s in rows
]))
"""

_GTE_PLACEHOLDER = [
    "PRESENT",
    "thenlper/gte-small",
    384,
    False,
    "",
    "",
    "danswer_chunk",
]


@pytest.mark.parametrize(
    "env,expected",
    [
        # Fresh default: the gte-small placeholder plus a granite FUTURE row.
        (
            {},
            [
                _GTE_PLACEHOLDER,
                [
                    "FUTURE",
                    GRANITE,
                    384,
                    True,
                    "",
                    "",
                    "danswer_chunk_ibm_granite_granite_embedding_97m_multilingual_r2",
                ],
            ],
        ),
        # nomic via env (the previous default) seeds exactly what main seeded.
        (
            {"DOCUMENT_ENCODER_MODEL": NOMIC},
            [
                _GTE_PLACEHOLDER,
                [
                    "FUTURE",
                    NOMIC,
                    768,
                    True,
                    "search_query: ",
                    "search_document: ",
                    "danswer_chunk_nomic_ai_nomic_embed_text_v1",
                ],
            ],
        ),
        # Any other model via env is an override: PRESENT on danswer_chunk.
        (
            {"DOCUMENT_ENCODER_MODEL": "my-org/custom-model"},
            [
                [
                    "PRESENT",
                    "my-org/custom-model",
                    768,
                    True,
                    "search_query: ",
                    "search_document: ",
                    "danswer_chunk",
                ]
            ],
        ),
        # nomic-era settings without DOCUMENT_ENCODER_MODEL: a working granite
        # row, not granite with nomic's 768 dims and prefixes.
        (
            {
                "DOC_EMBEDDING_DIM": "768",
                "ASYM_QUERY_PREFIX": "search_query: ",
                "ASYM_PASSAGE_PREFIX": "search_document: ",
            },
            [
                _GTE_PLACEHOLDER,
                [
                    "FUTURE",
                    GRANITE,
                    384,
                    True,
                    "",
                    "",
                    "danswer_chunk_ibm_granite_granite_embedding_97m_multilingual_r2",
                ],
            ],
        ),
    ],
    ids=["no-env", "nomic-env", "custom-env", "partial-nomic-env"],
)
def test_alembic_dbaa756c2ccf_seed(
    env: dict[str, str], expected: list[list[object]]
) -> None:
    assert _last_json_line(_run_python(_SEED_PROBE, env)) == expected
