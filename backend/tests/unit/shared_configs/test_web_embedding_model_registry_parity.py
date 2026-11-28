"""The web model picker mirrors the backend embedding model registry.

The admin page sends a model's name, dimension, normalize flag and prefixes
as-is to set-new-search-settings, and the upgrade-only guard rejects a
selectable model whose values differ from the backend registry. So the two
copies must agree, and a model the backend treats as legacy must be marked
legacy in the web registry (the picker hides it)."""

import re
from pathlib import Path

from shared_configs.embedding_models import (
    EMBEDDING_MODEL_SPECS,
    EmbeddingModelStatus,
)
from shared_configs.enums import EmbeddingProvider

_WEB_REGISTRY = (
    Path(__file__).resolve().parents[4]
    / "web"
    / "src"
    / "lib"
    / "searchSettings"
    / "constants.ts"
)
_GROUP = re.compile(r"providerName:\s*EmbeddingProviderName\.(\w+)")
# Model objects hold no nested braces.
_MODEL_BLOCK = re.compile(r"\{([^{}]*\bmodelName:[^{}]*)\}")

# (provider_type, model_name) -> (dim, normalize, query_prefix, passage_prefix,
# legacy). Legacy values are informational only, so a legacy entry keeps only
# its legacy flag.
_ModelKey = tuple[EmbeddingProvider | None, str]
_ModelValues = tuple[int | None, bool | None, str | None, str | None, bool]


def _field(block: str, name: str, value_pattern: str) -> str:
    match = re.search(rf"\b{name}:\s*{value_pattern}", block)
    assert match, f"No literal `{name}` in a model of {_WEB_REGISTRY.name}:\n{block}"
    return match.group(1)


def _web_models() -> dict[_ModelKey, _ModelValues]:
    source = _WEB_REGISTRY.read_text()
    source = source[: source.index("export const CUSTOM_PROVIDER")]
    self_hosted_start = source.index("export const SELF_HOSTED_PROVIDERS")
    groups = list(_GROUP.finditer(source))
    group_ends = [group.start() for group in groups[1:]] + [len(source)]
    models: dict[_ModelKey, _ModelValues] = {}
    for group, end in zip(groups, group_ends, strict=True):
        # Self-hosted groups have provider_type None on the backend.
        provider_type = (
            None
            if group.start() > self_hosted_start
            else EmbeddingProvider(group.group(1).lower())
        )
        for block in _MODEL_BLOCK.findall(source[group.end() : end]):
            key = (provider_type, _field(block, "modelName", r'"([^"]*)"'))
            assert key not in models, f"Duplicate model {key} in the web registry"
            if re.search(r"\blegacy:\s*true\b", block):
                models[key] = (None, None, None, None, True)
                continue
            models[key] = (
                int(_field(block, "modelDim", r"(\d+)")),
                _field(block, "normalize", r"(true|false)") == "true",
                _field(block, "queryPrefix", r'"([^"]*)"'),
                _field(block, "passagePrefix", r'"([^"]*)"'),
                False,
            )
    return models


def test_web_registry_matches_the_backend_registry() -> None:
    expected: dict[_ModelKey, _ModelValues] = {
        (spec.provider_type, spec.model_name): (
            (None, None, None, None, True)
            if spec.status == EmbeddingModelStatus.LEGACY
            else (
                spec.model_dim,
                spec.normalize,
                spec.query_prefix,
                spec.passage_prefix,
                False,
            )
        )
        for spec in EMBEDDING_MODEL_SPECS
    }

    assert _web_models() == expected
