"""Integrity of the shared embedding-model registry."""

import re
import subprocess
import sys
from pathlib import Path

from shared_configs.embedding_models import (
    EMBEDDING_MODEL_SPECS,
    EmbeddingModelStatus,
    LocalModelLoader,
)

_BACKEND_DIR = Path(__file__).resolve().parents[3]


def test_registry_invariants() -> None:
    for spec in EMBEDDING_MODEL_SPECS:
        # get_local_model_spec only matches pinned entries, so a selectable
        # self-hosted model without a revision would get the legacy load.
        needs_revision = spec.provider_type is None and (
            spec.status == EmbeddingModelStatus.SELECTABLE
        )
        assert (spec.hf_revision is not None) == needs_revision, spec.model_name
        if spec.hf_revision is not None:
            assert re.fullmatch(r"[0-9a-f]{40}", spec.hf_revision), spec.model_name
        if spec.provider_type is not None:
            # The cloud path refuses prefixes, and loader settings are local-only.
            assert spec.query_prefix == spec.passage_prefix == "", spec.model_name
            assert spec.normalize is False, spec.model_name
            assert spec.loader == LocalModelLoader.STANDARD, spec.model_name


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
