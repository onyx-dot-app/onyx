"""The first search settings rows of a fresh DB (alembic dbaa756c2ccf) and the
default tokenizer, which onyx.configs.model_configs derives from the env and the
embedding registry."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_MODEL_ENV_VARS = (
    "DOCUMENT_ENCODER_MODEL",
    "DOC_EMBEDDING_DIM",
    "NORMALIZE_EMBEDDINGS",
    "ASYM_QUERY_PREFIX",
    "ASYM_PASSAGE_PREFIX",
)

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


# Loads alembic dbaa756c2ccf from its file and prints the default tokenizer and
# the rows that the migration seeds.
_SEED_PROBE = """
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "seed", "alembic/versions/dbaa756c2ccf_embedding_models.py"
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
from onyx.configs.model_configs import DEFAULT_TOKENIZER_MODEL

rows = [["PRESENT", migration._get_old_default_embedding_model()]]
if not migration.user_has_overridden_embedding_model():
    rows.append(["FUTURE", migration._get_new_default_embedding_model()])
print(json.dumps([DEFAULT_TOKENIZER_MODEL, [
    [status, s.model_name, s.model_dim, s.normalize, s.query_prefix,
     s.passage_prefix, s.index_name]
    for status, s in rows
]]))
"""

NOMIC = "nomic-ai/nomic-embed-text-v1"
CUSTOM = "my-org/custom-model"
_GTE_PLACEHOLDER = [
    "PRESENT",
    "thenlper/gte-small",
    384,
    False,
    "",
    "",
    "danswer_chunk",
]
_GRANITE_FUTURE = [
    "FUTURE",
    "ibm-granite/granite-embedding-97m-multilingual-r2",
    384,
    True,
    "",
    "",
    "danswer_chunk_ibm_granite_granite_embedding_97m_multilingual_r2",
]


@pytest.mark.parametrize(
    "env,tokenizer,rows",
    [
        # Fresh default: the gte-small placeholder plus a granite FUTURE row, from
        # granite's registry spec. The tokenizer stays nomic.
        ({}, NOMIC, [_GTE_PLACEHOLDER, _GRANITE_FUTURE]),
        # nomic via env (the previous default) seeds exactly what main seeded.
        (
            {"DOCUMENT_ENCODER_MODEL": NOMIC},
            NOMIC,
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
        # Any other model via env is an override: PRESENT on danswer_chunk, with
        # the model env vars over the old literal defaults.
        (
            {"DOCUMENT_ENCODER_MODEL": CUSTOM, "DOC_EMBEDDING_DIM": "1024"},
            CUSTOM,
            [
                [
                    "PRESENT",
                    CUSTOM,
                    1024,
                    True,
                    "search_query: ",
                    "search_document: ",
                    "danswer_chunk",
                ]
            ],
        ),
        # An env file written for nomic, without DOCUMENT_ENCODER_MODEL: a working
        # granite row, not granite with nomic's 768 dims and prefixes.
        (
            {
                "DOC_EMBEDDING_DIM": "768",
                "ASYM_QUERY_PREFIX": "search_query: ",
                "ASYM_PASSAGE_PREFIX": "search_document: ",
            },
            NOMIC,
            [_GTE_PLACEHOLDER, _GRANITE_FUTURE],
        ),
    ],
    ids=["no-env", "nomic-env", "custom-env", "nomic-era-env-without-model"],
)
def test_alembic_dbaa756c2ccf_seed(
    env: dict[str, str], tokenizer: str, rows: list[list[object]]
) -> None:
    assert _last_json_line(_run_python(_SEED_PROBE, env)) == [tokenizer, rows]
