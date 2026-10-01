"""The model-server image must bake exactly the registry's bundled models."""

import re
from pathlib import Path

from shared_configs.configs import DEFAULT_DOCUMENT_ENCODER_MODEL
from shared_configs.embedding_models import (
    bundled_local_model_names,
    get_local_model_spec,
)

_MODEL_SERVER_DOCKERFILE = (
    Path(__file__).resolve().parents[3] / "Dockerfile.model_server"
)
_BAKED_NAME_PATTERN = re.compile(r"model_name_or_path='(?P<name>[^']+)'")
_BAKE_PATTERN = re.compile(
    r"SentenceTransformer\(model_name_or_path='(?P<name>[^']+)',\s*\\?\s*"
    r"revision='(?P<revision>[^']+)',\s*trust_remote_code=False\)"
)


def test_dockerfile_bakes_bundled_models_at_pinned_revision() -> None:
    text = _MODEL_SERVER_DOCKERFILE.read_text()
    expected: dict[str, str] = {}
    for model_name in bundled_local_model_names():
        spec = get_local_model_spec(model_name)
        assert spec is not None and spec.hf_revision is not None
        expected[model_name] = spec.hf_revision

    baked = {
        match.group("name"): match.group("revision")
        for match in _BAKE_PATTERN.finditer(text)
    }
    assert baked == expected
    # No other model (e.g. nomic-ai/nomic-embed-text-v1) is baked.
    all_baked_names = {m.group("name") for m in _BAKED_NAME_PATTERN.finditer(text)}
    assert all_baked_names == set(expected)
    assert DEFAULT_DOCUMENT_ENCODER_MODEL in expected
