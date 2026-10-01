"""The web model picker mirrors the backend embedding model registry.

The admin page sends a model's name, dimension, normalize flag and prefixes
as-is to set-new-search-settings, and the upgrade-only guard rejects a
selectable model whose values differ from the backend registry. So the two
copies must agree, and a model the backend treats as legacy must be marked
legacy in the web registry (the picker hides it). This parses the web registry
source and pins the two together.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from shared_configs.embedding_models import (
    EMBEDDING_MODEL_SPECS,
    EmbeddingModelSpec,
    EmbeddingModelStatus,
)
from shared_configs.enums import EmbeddingProvider

WEB_REGISTRY = (
    Path(__file__).resolve().parents[4]
    / "web"
    / "src"
    / "lib"
    / "searchSettings"
    / "constants.ts"
)

# The web registry's cloud group values that map to a backend provider_type.
# Every self-hosted group is provider_type None on the backend.
_CLOUD_GROUP_TO_PROVIDER = {
    "COHERE": EmbeddingProvider.COHERE,
    "OPENAI": EmbeddingProvider.OPENAI,
    "GOOGLE": EmbeddingProvider.GOOGLE,
    "VOYAGE": EmbeddingProvider.VOYAGE,
    "LITELLM": EmbeddingProvider.LITELLM,
    "AZURE": EmbeddingProvider.AZURE,
}

# A double-quoted TS string literal, with escapes.
_TS_STRING = r'"((?:[^"\\]|\\.)*)"'


@dataclass(frozen=True)
class _WebModel:
    group: str
    provider_type: EmbeddingProvider | None
    model_name: str
    model_dim: int
    normalize: bool
    query_prefix: str
    passage_prefix: str
    legacy: bool


def _unescape(value: str) -> str:
    return re.sub(r"\\(.)", r"\1", value)


def _required(pattern: str, block: str, field: str, group: str) -> str:
    match = re.search(pattern, block)
    if match is None:
        raise AssertionError(
            f"Could not read `{field}` of a model in the {group} group of "
            f"{WEB_REGISTRY.name}. Registry models must spell out every field "
            f"with a double-quoted or literal value. Model source:\n{block}"
        )
    return match.group(1)


def _parse_model(
    block: str, group: str, provider_type: EmbeddingProvider | None
) -> _WebModel:
    def string_field(field: str) -> str:
        return _unescape(_required(rf"\b{field}:\s*{_TS_STRING}", block, field, group))

    return _WebModel(
        group=group,
        provider_type=provider_type,
        model_name=string_field("modelName"),
        model_dim=int(_required(r"\bmodelDim:\s*(\d+)", block, "modelDim", group)),
        normalize=_required(r"\bnormalize:\s*(true|false)\b", block, "normalize", group)
        == "true",
        query_prefix=string_field("queryPrefix"),
        passage_prefix=string_field("passagePrefix"),
        legacy=re.search(r"\blegacy:\s*true\b", block) is not None,
    )


def _parse_models(section: str, cloud: bool) -> list[_WebModel]:
    models: list[_WebModel] = []
    group_matches = list(
        re.finditer(r"providerName:\s*EmbeddingProviderName\.(\w+)", section)
    )
    for i, group_match in enumerate(group_matches):
        group = group_match.group(1)
        end = (
            group_matches[i + 1].start() if i + 1 < len(group_matches) else len(section)
        )
        group_source = section[group_match.end() : end]
        if cloud:
            assert group in _CLOUD_GROUP_TO_PROVIDER, (
                f"Unknown cloud group {group} in {WEB_REGISTRY.name}"
            )
            provider_type: EmbeddingProvider | None = _CLOUD_GROUP_TO_PROVIDER[group]
        else:
            assert group not in _CLOUD_GROUP_TO_PROVIDER, (
                f"Self-hosted group {group} reuses a cloud provider value, so the "
                "page would route its models to that cloud API."
            )
            provider_type = None
        # Model objects hold no nested braces.
        models.extend(
            _parse_model(block, group, provider_type)
            for block in re.findall(r"\{([^{}]*\bmodelName:[^{}]*)\}", group_source)
        )
    return models


def _web_models() -> list[_WebModel]:
    source = WEB_REGISTRY.read_text()
    cloud_start = source.index("export const CLOUD_BASED_PROVIDERS")
    self_hosted_start = source.index("export const SELF_HOSTED_PROVIDERS")
    custom_start = source.index("export const CUSTOM_PROVIDER")
    assert cloud_start < self_hosted_start < custom_start, (
        f"Unexpected section order in {WEB_REGISTRY.name}"
    )
    return _parse_models(
        source[cloud_start:self_hosted_start], cloud=True
    ) + _parse_models(source[self_hosted_start:custom_start], cloud=False)


def _key(provider_type: EmbeddingProvider | None, model_name: str) -> tuple[str, str]:
    return (provider_type.value if provider_type else "self-hosted", model_name)


@pytest.fixture(scope="module")
def web_models_by_key() -> dict[tuple[str, str], _WebModel]:
    models = _web_models()
    by_key = {_key(m.provider_type, m.model_name): m for m in models}
    assert len(by_key) == len(models), "Duplicate model in the web registry"
    return by_key


def test_parser_reads_the_web_registry(
    web_models_by_key: dict[tuple[str, str], _WebModel],
) -> None:
    # Guards against a parser that silently matches nothing.
    assert len(web_models_by_key) >= len(EMBEDDING_MODEL_SPECS)
    assert any(m.query_prefix.endswith(" ") for m in web_models_by_key.values())


@pytest.mark.parametrize(
    "spec",
    [s for s in EMBEDDING_MODEL_SPECS if s.status == EmbeddingModelStatus.SELECTABLE],
    ids=lambda spec: spec.model_name,
)
def test_selectable_model_matches_web_registry(
    spec: EmbeddingModelSpec,
    web_models_by_key: dict[tuple[str, str], _WebModel],
) -> None:
    web = web_models_by_key.get(_key(spec.provider_type, spec.model_name))
    assert web is not None, (
        f"Selectable model {spec.model_name} is missing from {WEB_REGISTRY.name}"
    )
    assert not web.legacy, f"{spec.model_name} is selectable but marked legacy on web"
    assert (
        web.model_dim,
        web.normalize,
        web.query_prefix,
        web.passage_prefix,
    ) == (
        spec.model_dim,
        spec.normalize,
        spec.query_prefix,
        spec.passage_prefix,
    )


@pytest.mark.parametrize(
    "spec",
    [s for s in EMBEDDING_MODEL_SPECS if s.status == EmbeddingModelStatus.LEGACY],
    ids=lambda spec: spec.model_name,
)
def test_legacy_model_is_marked_legacy_on_web(
    spec: EmbeddingModelSpec,
    web_models_by_key: dict[tuple[str, str], _WebModel],
) -> None:
    web = web_models_by_key.get(_key(spec.provider_type, spec.model_name))
    assert web is not None, (
        f"Legacy model {spec.model_name} is missing from {WEB_REGISTRY.name}. "
        "Existing deployments can still use it, so the page must display it."
    )
    assert web.legacy, f"{spec.model_name} is legacy but selectable on web"


def test_every_web_registry_model_is_in_the_backend_registry(
    web_models_by_key: dict[tuple[str, str], _WebModel],
) -> None:
    """A web-only model would reach the backend unpinned (self-hosted) or be
    rejected by the guard (cloud)."""
    backend_keys = {_key(s.provider_type, s.model_name) for s in EMBEDDING_MODEL_SPECS}
    assert set(web_models_by_key) - backend_keys == set()
