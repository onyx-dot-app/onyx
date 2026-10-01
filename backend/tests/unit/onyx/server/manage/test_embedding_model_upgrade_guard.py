"""Upgrade-only guard in set_new_search_settings: a new embedding target must be the
PRESENT model (same-model re-index) or a selectable registry model. Legacy registry
models are refused; custom self-hosted models, LiteLLM and Azure stay open. A new
selectable cloud model is probed before the PRESENT row lock."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.context.search.models import (
    SavedSearchSettings,
    SearchSettingsCreationRequest,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.search_settings import (
    _probe_cloud_embedding_model,
    set_new_search_settings,
)
from shared_configs.configs import ALT_INDEX_SUFFIX
from shared_configs.embedding_models import (
    DEFAULT_LOCAL_EMBEDDING_MODEL_NAME,
    EmbeddingModelSpec,
    find_embedding_model_spec,
    selectable_embedding_model_specs,
)
from shared_configs.enums import EmbeddingProvider, EmbedTextType
from shared_configs.utils import clean_model_name

_MODULE = "onyx.server.manage.search_settings"

NOMIC = "nomic-ai/nomic-embed-text-v1"
GRANITE = DEFAULT_LOCAL_EMBEDDING_MODEL_NAME


class _GuardPassed(Exception):
    """Patched into create_search_settings to prove the guards let the request through."""


def _spec(
    provider_type: EmbeddingProvider | None, model_name: str
) -> EmbeddingModelSpec:
    spec = find_embedding_model_spec(provider_type, model_name)
    assert spec is not None
    return spec


def _request(
    model_name: str,
    *,
    provider_type: EmbeddingProvider | None = None,
    model_dim: int = 768,
    normalize: bool = True,
    query_prefix: str | None = "",
    passage_prefix: str | None = "",
    reduced_dimension: int | None = None,
) -> SearchSettingsCreationRequest:
    return SearchSettingsCreationRequest(
        model_name=model_name,
        model_dim=model_dim,
        normalize=normalize,
        query_prefix=query_prefix,
        passage_prefix=passage_prefix,
        provider_type=provider_type,
        index_name=None,
        multipass_indexing=False,
        reduced_dimension=reduced_dimension,
        enable_contextual_rag=False,
        contextual_rag_model_configuration_id=None,
    )


def _spec_request(
    provider_type: EmbeddingProvider | None,
    model_name: str,
    **overrides: Any,
) -> SearchSettingsCreationRequest:
    """A request with the registry's settings for the model, as the UI sends it."""
    spec = _spec(provider_type, model_name)
    values: dict[str, Any] = {
        "provider_type": spec.provider_type,
        "model_dim": spec.model_dim,
        "normalize": spec.normalize,
        "query_prefix": spec.query_prefix,
        "passage_prefix": spec.passage_prefix,
    }
    values.update(overrides)
    return _request(model_name, **values)


def _present(
    model_name: str,
    provider_type: EmbeddingProvider | None = None,
    *,
    model_dim: int | None = None,
    reduced_dimension: int | None = None,
) -> MagicMock:
    """PRESENT row. model_dim defaults to the registry dim, else 768."""
    if model_dim is None:
        spec = find_embedding_model_spec(provider_type, model_name)
        model_dim = spec.model_dim if spec is not None else 768
    present = MagicMock()
    present.id = 2
    present.use_port_flow = False
    present.port_backfill_source_id = None
    present.model_name = model_name
    present.provider_type = provider_type
    present.model_dim = model_dim
    present.reduced_dimension = reduced_dimension
    present.index_name = f"danswer_chunk_{clean_model_name(model_name)}"
    return present


@dataclass
class _EndpointMocks:
    provider: MagicMock
    current: MagicMock
    secondary: MagicMock
    create: MagicMock
    probe: MagicMock

    def set_present(self, present: MagicMock) -> None:
        self.current.return_value = present

    def created_settings(self) -> SavedSearchSettings:
        self.create.assert_called_once()
        return self.create.call_args.kwargs["search_settings"]


@pytest.fixture
def mocks() -> Iterator[_EndpointMocks]:
    with (
        patch(f"{_MODULE}.validate_contextual_rag_model"),
        patch(f"{_MODULE}._validate_vector_quantization_supported"),
        patch(f"{_MODULE}.get_embedding_provider_from_provider_type") as provider,
        patch(f"{_MODULE}.get_current_search_settings") as current,
        patch(
            f"{_MODULE}.get_secondary_search_settings", return_value=None
        ) as secondary,
        patch(f"{_MODULE}.port_backfill_has_pending_work", return_value=False),
        patch(f"{_MODULE}._guard_index_name_reuse"),
        patch(f"{_MODULE}.compute_wont_port_cc_pair_ids", return_value=[]),
        patch(f"{_MODULE}.set_reclaim_intent_on_current__no_commit"),
        patch(f"{_MODULE}.create_search_settings", side_effect=_GuardPassed) as create,
        patch(f"{_MODULE}._probe_cloud_embedding_model") as probe,
    ):
        yield _EndpointMocks(
            provider=provider,
            current=current,
            secondary=secondary,
            create=create,
            probe=probe,
        )


def _submit(request: SearchSettingsCreationRequest) -> None:
    set_new_search_settings(request, _=MagicMock(), db_session=MagicMock())


def _assert_allowed(request: SearchSettingsCreationRequest) -> None:
    with pytest.raises(_GuardPassed):
        _submit(request)


def _assert_rejected(
    mocks: _EndpointMocks, request: SearchSettingsCreationRequest
) -> str:
    with pytest.raises(OnyxError) as exc:
        _submit(request)
    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    mocks.create.assert_not_called()
    mocks.probe.assert_not_called()
    return exc.value.detail


# ---- Rule 1: same model as PRESENT ----


def test_legacy_present_same_model_reindex_allowed(mocks: _EndpointMocks) -> None:
    # Real nomic rows often have empty prefixes; the registry is never compared.
    mocks.set_present(_present(NOMIC))

    _assert_allowed(_request(NOMIC, model_dim=768, query_prefix="", passage_prefix=""))

    created = mocks.created_settings()
    assert created.model_name == NOMIC
    assert (
        created.index_name
        == f"danswer_chunk_{clean_model_name(NOMIC)}{ALT_INDEX_SUFFIX}"
    )
    mocks.probe.assert_not_called()


def test_same_model_reindex_matches_case_and_punctuation_variants(
    mocks: _EndpointMocks,
) -> None:
    mocks.set_present(_present("intfloat/e5-base-v2"))

    _assert_allowed(_request("IntFloat/E5_Base.V2"))

    # Rule 1 passes a legacy or custom request through unchanged.
    assert mocks.created_settings().model_name == "IntFloat/E5_Base.V2"


@pytest.mark.parametrize(
    "provider_type,model_name,variant",
    [
        (None, "voyageai/voyage-4-nano", "VoyageAI/Voyage-4-Nano"),
        (None, GRANITE, GRANITE.upper()),
        (EmbeddingProvider.COHERE, "embed-v5.0-pro", "Embed-V5.0-Pro"),
    ],
)
def test_same_model_reindex_of_selectable_model_stores_the_canonical_name(
    mocks: _EndpointMocks,
    provider_type: EmbeddingProvider | None,
    model_name: str,
    variant: str,
) -> None:
    """The model server and the tokenizer match registry names exactly. A variant
    would load without the pinned revision and the model's fix-ups."""
    mocks.set_present(_present(model_name, provider_type))

    _assert_allowed(
        _spec_request(provider_type, model_name).model_copy(
            update={"model_name": variant}
        )
    )

    created = mocks.created_settings()
    assert created.model_name == model_name
    assert created.index_name == (
        f"danswer_chunk_{clean_model_name(model_name)}{ALT_INDEX_SUFFIX}"
    )
    mocks.probe.assert_not_called()


def test_same_model_reindex_keeps_a_custom_dim_of_a_registry_name(
    mocks: _EndpointMocks,
) -> None:
    """A custom voyage-4-nano added before the registry (1024 dims) can still
    re-index with its own settings."""
    mocks.set_present(_present("voyageai/voyage-4-nano", model_dim=1024))

    _assert_allowed(_request("voyageai/voyage-4-nano", model_dim=1024))

    created = mocks.created_settings()
    assert created.model_name == "voyageai/voyage-4-nano"
    assert created.model_dim == 1024


def test_same_model_reindex_can_move_a_custom_row_to_the_registry_dim(
    mocks: _EndpointMocks,
) -> None:
    mocks.set_present(_present("voyageai/voyage-4-nano", model_dim=1024))

    _assert_allowed(_spec_request(None, "voyageai/voyage-4-nano"))

    assert mocks.created_settings().model_dim == 2048


@pytest.mark.parametrize(
    ("present_name", "provider_type", "bad_dim"),
    [
        ("ibm-granite/granite-embedding-97m-multilingual-r2", None, 768),
        ("nomic-ai/nomic-embed-text-v1", None, 384),
        ("embed-english-v3.0", EmbeddingProvider.COHERE, 1536),
    ],
)
def test_same_model_reindex_with_another_dim_rejected(
    mocks: _EndpointMocks,
    present_name: str,
    provider_type: EmbeddingProvider | None,
    bad_dim: int,
) -> None:
    """A wrong dim would create an index that the model's vectors never fit."""
    mocks.set_present(_present(present_name, provider_type))

    detail = _assert_rejected(
        mocks, _request(present_name, provider_type=provider_type, model_dim=bad_dim)
    )

    assert "must keep its dimension" in detail


def test_same_model_reindex_cannot_change_reduced_dimension_in_multi_tenant(
    mocks: _EndpointMocks,
) -> None:
    """Tenants share the index of a model, so one tenant's reduced_dimension
    would break every other tenant's re-index."""
    model_name = "ibm-granite/granite-embedding-97m-multilingual-r2"
    mocks.set_present(_present(model_name))

    with patch(f"{_MODULE}.MULTI_TENANT", True):
        detail = _assert_rejected(
            mocks, _spec_request(None, model_name, reduced_dimension=256)
        )

    assert "shared" in detail or "share" in detail


def test_same_model_reindex_keeps_reduced_dimension_in_multi_tenant(
    mocks: _EndpointMocks,
) -> None:
    mocks.set_present(
        _present(
            "text-embedding-3-large", EmbeddingProvider.OPENAI, reduced_dimension=1024
        )
    )

    with patch(f"{_MODULE}.MULTI_TENANT", True):
        _assert_allowed(
            _spec_request(
                EmbeddingProvider.OPENAI,
                "text-embedding-3-large",
                reduced_dimension=1024,
            )
        )


def test_legacy_cloud_present_same_model_reindex_allowed_without_probe(
    mocks: _EndpointMocks,
) -> None:
    mocks.set_present(_present("embed-english-v3.0", EmbeddingProvider.COHERE))

    _assert_allowed(
        _request(
            "embed-english-v3.0",
            provider_type=EmbeddingProvider.COHERE,
            model_dim=1024,
            normalize=True,
        )
    )

    mocks.probe.assert_not_called()


def test_removed_legacy_model_present_same_model_reindex_allowed(
    mocks: _EndpointMocks,
) -> None:
    mocks.set_present(_present("text-embedding-004", EmbeddingProvider.GOOGLE))

    _assert_allowed(
        _request("text-embedding-004", provider_type=EmbeddingProvider.GOOGLE)
    )


def test_same_model_needs_same_provider(mocks: _EndpointMocks) -> None:
    # Self-hosted PRESENT with a registry cloud name is not the same model.
    mocks.set_present(_present("embed-english-v3.0"))

    _assert_rejected(
        mocks,
        _request(
            "embed-english-v3.0", provider_type=EmbeddingProvider.COHERE, model_dim=1024
        ),
    )


# ---- Rule 2: selectable registry models ----


@pytest.mark.parametrize(
    "spec", selectable_embedding_model_specs(), ids=lambda spec: spec.model_name
)
def test_every_selectable_model_is_allowed_with_registry_settings(
    mocks: _EndpointMocks, spec: EmbeddingModelSpec
) -> None:
    mocks.set_present(_present(NOMIC))

    _assert_allowed(_spec_request(spec.provider_type, spec.model_name))

    created = mocks.created_settings()
    assert created.model_name == spec.model_name
    assert created.index_name == f"danswer_chunk_{clean_model_name(spec.model_name)}"
    if spec.provider_type is None:
        mocks.probe.assert_not_called()
    else:
        mocks.probe.assert_called_once()


def test_selectable_model_name_is_canonicalized(mocks: _EndpointMocks) -> None:
    mocks.set_present(_present(NOMIC))

    _assert_allowed(
        _spec_request(None, GRANITE).model_copy(
            update={
                "model_name": "  IBM-Granite/Granite-Embedding-97M-Multilingual-R2 "
            }
        )
    )

    created = mocks.created_settings()
    assert created.model_name == GRANITE
    assert (
        created.index_name
        == "danswer_chunk_ibm_granite_granite_embedding_97m_multilingual_r2"
    )


def test_selectable_model_accepts_null_prefixes_for_empty_registry_prefixes(
    mocks: _EndpointMocks,
) -> None:
    mocks.set_present(_present(NOMIC))

    _assert_allowed(
        _spec_request(None, GRANITE, query_prefix=None, passage_prefix=None)
    )


@pytest.mark.parametrize(
    ("overrides", "expected_problem"),
    [
        ({"model_dim": 768}, "model_dim must be 384"),
        ({"normalize": False}, "normalize must be True"),
        ({"query_prefix": "query: "}, "query_prefix must be ''"),
        ({"passage_prefix": "passage: "}, "passage_prefix must be ''"),
    ],
)
def test_selectable_model_with_wrong_settings_rejected(
    mocks: _EndpointMocks, overrides: dict[str, Any], expected_problem: str
) -> None:
    mocks.set_present(_present(NOMIC))

    detail = _assert_rejected(mocks, _spec_request(None, GRANITE, **overrides))

    assert expected_problem in detail


def test_selectable_prefixes_must_match_exactly(mocks: _EndpointMocks) -> None:
    mocks.set_present(_present(NOMIC))

    # The registry prefix has a trailing space.
    detail = _assert_rejected(
        mocks,
        _spec_request(None, "nvidia/Nemotron-3-Embed-1B-BF16", query_prefix="query:"),
    )

    assert "query_prefix must be 'query: '" in detail


# ---- reduced_dimension ----


@pytest.mark.parametrize(
    ("provider_type", "model_name", "reduced_dimension"),
    [
        (EmbeddingProvider.OPENAI, "text-embedding-3-large", 1024),
        (EmbeddingProvider.OPENAI, "text-embedding-3-small", 512),
        (EmbeddingProvider.GOOGLE, "gemini-embedding-2", 768),
    ],
)
def test_reduced_dimension_allowed_for_supporting_models(
    mocks: _EndpointMocks,
    provider_type: EmbeddingProvider,
    model_name: str,
    reduced_dimension: int,
) -> None:
    mocks.set_present(_present(NOMIC))

    _assert_allowed(
        _spec_request(provider_type, model_name, reduced_dimension=reduced_dimension)
    )

    assert mocks.created_settings().reduced_dimension == reduced_dimension


@pytest.mark.parametrize("reduced_dimension", [0, -1, 3072, 4096])
def test_reduced_dimension_out_of_range_rejected(
    mocks: _EndpointMocks, reduced_dimension: int
) -> None:
    mocks.set_present(_present(NOMIC))

    detail = _assert_rejected(
        mocks,
        _spec_request(
            EmbeddingProvider.OPENAI,
            "text-embedding-3-large",
            reduced_dimension=reduced_dimension,
        ),
    )

    assert "reduced_dimension must be between 1 and 3071" in detail


@pytest.mark.parametrize(
    ("provider_type", "model_name"),
    [
        (EmbeddingProvider.COHERE, "embed-v5.0-pro"),
        (EmbeddingProvider.COHERE, "embed-v5.0-fast"),
        (None, GRANITE),
        (None, "voyageai/voyage-4-nano"),
        (None, "nvidia/Nemotron-3-Embed-1B-BF16"),
    ],
)
def test_reduced_dimension_rejected_for_models_without_support(
    mocks: _EndpointMocks,
    provider_type: EmbeddingProvider | None,
    model_name: str,
) -> None:
    mocks.set_present(_present(NOMIC))

    detail = _assert_rejected(
        mocks, _spec_request(provider_type, model_name, reduced_dimension=256)
    )

    assert "does not support reduced_dimension" in detail


def test_reduced_dimension_rejected_in_multi_tenant(mocks: _EndpointMocks) -> None:
    mocks.set_present(_present("embed-english-v3.0", EmbeddingProvider.COHERE))

    with patch(f"{_MODULE}.MULTI_TENANT", True):
        detail = _assert_rejected(
            mocks,
            _spec_request(
                EmbeddingProvider.OPENAI,
                "text-embedding-3-large",
                reduced_dimension=1024,
            ),
        )

    assert "not supported in Onyx Cloud" in detail


def test_selectable_model_without_reduced_dimension_allowed_in_multi_tenant(
    mocks: _EndpointMocks,
) -> None:
    mocks.set_present(_present("embed-english-v3.0", EmbeddingProvider.COHERE))

    with patch(f"{_MODULE}.MULTI_TENANT", True):
        _assert_allowed(_spec_request(EmbeddingProvider.COHERE, "embed-v5.0-pro"))


# ---- Rules 3 and 4: legacy and unknown registry-provider models ----


@pytest.mark.parametrize(
    ("provider_type", "model_name"),
    [
        (None, NOMIC),
        (None, "intfloat/e5-base-v2"),
        (None, "intfloat/multilingual-e5-small"),
        # Removed from the UI long ago, still refused.
        (None, "thenlper/gte-small"),
        (EmbeddingProvider.COHERE, "embed-english-v3.0"),
        (EmbeddingProvider.COHERE, "embed-v4.0"),
        (EmbeddingProvider.GOOGLE, "gemini-embedding-001"),
        (EmbeddingProvider.GOOGLE, "text-embedding-005"),
        (EmbeddingProvider.GOOGLE, "gemini-embedding-2-preview"),
        (EmbeddingProvider.GOOGLE, "text-embedding-004"),
        (EmbeddingProvider.GOOGLE, "textembedding-gecko@003"),
        (EmbeddingProvider.VOYAGE, "voyage-large-2-instruct"),
    ],
)
def test_legacy_target_rejected(
    mocks: _EndpointMocks,
    provider_type: EmbeddingProvider | None,
    model_name: str,
) -> None:
    mocks.set_present(_present(GRANITE))

    detail = _assert_rejected(mocks, _spec_request(provider_type, model_name))

    assert "legacy embedding model" in detail
    # The message names the models the admin can choose instead.
    for spec in selectable_embedding_model_specs():
        assert spec.model_name in detail


@pytest.mark.parametrize(
    "model_name",
    [
        "Nomic-AI/Nomic-Embed-Text-V1",
        "  nomic-ai/nomic-embed-text-v1  ",
        "nomic_ai/nomic.embed.text.v1",
    ],
)
def test_legacy_self_hosted_variant_rejected(
    mocks: _EndpointMocks, model_name: str
) -> None:
    # Custom Model modal path: variants of a legacy name fold to the same key.
    mocks.set_present(_present(GRANITE))

    _assert_rejected(mocks, _request(model_name))


@pytest.mark.parametrize(
    ("provider_type", "model_name"),
    [
        (EmbeddingProvider.OPENAI, "text-embedding-ada-002"),
        (EmbeddingProvider.COHERE, "embed-multilingual-v3.0"),
        (EmbeddingProvider.VOYAGE, "voyage-3"),
        (EmbeddingProvider.GOOGLE, ""),
    ],
)
def test_unknown_model_of_registry_provider_rejected(
    mocks: _EndpointMocks,
    provider_type: EmbeddingProvider,
    model_name: str,
) -> None:
    mocks.set_present(_present(GRANITE))

    detail = _assert_rejected(mocks, _request(model_name, provider_type=provider_type))

    assert "not an embedding model that Onyx supports" in detail


def test_legacy_target_reports_conflict_first_while_reindex_in_progress(
    mocks: _EndpointMocks,
) -> None:
    mocks.set_present(_present(GRANITE))
    mocks.secondary.return_value = MagicMock()

    with pytest.raises(OnyxError) as exc:
        _submit(_request(NOMIC))

    assert exc.value.error_code == OnyxErrorCode.CONFLICT


# ---- Rule 5: open-world targets ----


@pytest.mark.parametrize(
    "model_name",
    ["my-org/custom-embedder", "sentence-transformers/all-MiniLM-L6-v2", "BAAI/bge-m3"],
)
def test_custom_self_hosted_model_allowed(
    mocks: _EndpointMocks, model_name: str
) -> None:
    mocks.set_present(_present(GRANITE))

    _assert_allowed(_request(model_name, model_dim=1024))

    assert mocks.created_settings().model_name == model_name
    mocks.probe.assert_not_called()


@pytest.mark.parametrize(
    ("provider_type", "model_name"),
    [
        (EmbeddingProvider.LITELLM, "my-proxy-embedder"),
        # Labels are free-form, so even a legacy-looking name is not checked.
        (EmbeddingProvider.LITELLM, "embed-english-v3.0"),
        (EmbeddingProvider.AZURE, "text-embedding-3-large"),
        (EmbeddingProvider.AZURE, "my-deployment"),
    ],
)
def test_litellm_and_azure_allowed_without_probe(
    mocks: _EndpointMocks,
    provider_type: EmbeddingProvider,
    model_name: str,
) -> None:
    mocks.set_present(_present(GRANITE))

    _assert_allowed(
        _request(model_name, provider_type=provider_type, model_dim=123, normalize=True)
    )

    created = mocks.created_settings()
    assert created.model_name == model_name
    assert created.model_dim == 123
    mocks.probe.assert_not_called()


def test_missing_cloud_provider_rejected(mocks: _EndpointMocks) -> None:
    mocks.set_present(_present(GRANITE))
    mocks.provider.return_value = None

    detail = _assert_rejected(
        mocks, _spec_request(EmbeddingProvider.COHERE, "embed-v5.0-pro")
    )

    assert "No embedding provider exists" in detail


# ---- Cloud probe placement ----


def _record_calls(mocks: _EndpointMocks, presents: dict[bool, MagicMock]) -> list[str]:
    """Records the order of PRESENT reads (unlocked / locked) and probes."""
    events: list[str] = []

    def _current(_db_session: MagicMock, *, for_update: bool = False) -> MagicMock:
        events.append("locked_read" if for_update else "unlocked_read")
        return presents[for_update]

    def _probe(*_args: object) -> None:
        events.append("probe")

    mocks.current.side_effect = _current
    mocks.probe.side_effect = _probe
    return events


def test_cloud_probe_runs_before_the_present_lock(mocks: _EndpointMocks) -> None:
    present = _present(GRANITE)
    events = _record_calls(mocks, {False: present, True: present})

    _assert_allowed(_spec_request(EmbeddingProvider.COHERE, "embed-v5.0-pro"))

    assert events == ["unlocked_read", "probe", "locked_read"]
    probed_request = mocks.probe.call_args.args[0]
    assert probed_request.model_name == "embed-v5.0-pro"
    assert mocks.probe.call_args.args[1] is mocks.provider.return_value


def test_cloud_probe_uses_canonical_name(mocks: _EndpointMocks) -> None:
    mocks.set_present(_present(GRANITE))

    _assert_allowed(
        _spec_request(EmbeddingProvider.COHERE, "embed-v5.0-pro").model_copy(
            update={"model_name": "Embed-V5.0-Pro"}
        )
    )

    assert mocks.probe.call_args.args[0].model_name == "embed-v5.0-pro"
    assert mocks.created_settings().model_name == "embed-v5.0-pro"


def test_cloud_probe_failure_blocks_the_reindex(mocks: _EndpointMocks) -> None:
    mocks.set_present(_present(GRANITE))
    mocks.probe.side_effect = OnyxError(OnyxErrorCode.INVALID_INPUT, "no access")

    with pytest.raises(OnyxError) as exc:
        _submit(_spec_request(EmbeddingProvider.GOOGLE, "gemini-embedding-2"))

    assert exc.value.detail == "no access"
    mocks.create.assert_not_called()
    # The failing probe ran before the lock, so nothing was locked.
    assert all(
        not call.kwargs.get("for_update") for call in mocks.current.call_args_list
    )


def test_same_model_cloud_reindex_is_not_probed(mocks: _EndpointMocks) -> None:
    mocks.set_present(_present("text-embedding-3-small", EmbeddingProvider.OPENAI))

    _assert_allowed(_spec_request(EmbeddingProvider.OPENAI, "text-embedding-3-small"))

    mocks.probe.assert_not_called()


def test_invalid_cloud_target_is_not_probed_and_conflict_comes_first(
    mocks: _EndpointMocks,
) -> None:
    mocks.set_present(_present(GRANITE))
    mocks.secondary.return_value = MagicMock()

    with pytest.raises(OnyxError) as exc:
        _submit(
            _spec_request(EmbeddingProvider.COHERE, "embed-v5.0-pro", model_dim=1024)
        )

    assert exc.value.error_code == OnyxErrorCode.CONFLICT
    mocks.probe.assert_not_called()


@pytest.mark.parametrize("conflict", ["secondary", "instant_backfill"])
def test_valid_cloud_target_is_not_probed_while_a_reindex_is_in_progress(
    mocks: _EndpointMocks, conflict: str
) -> None:
    present = _present(GRANITE)
    if conflict == "secondary":
        mocks.secondary.return_value = MagicMock()
    else:
        present.use_port_flow = True
        present.port_backfill_source_id = 1
    mocks.set_present(present)

    with (
        patch(f"{_MODULE}.port_backfill_has_pending_work", return_value=True),
        pytest.raises(OnyxError) as exc,
    ):
        _submit(_spec_request(EmbeddingProvider.GOOGLE, "gemini-embedding-2"))

    assert exc.value.error_code == OnyxErrorCode.CONFLICT
    mocks.probe.assert_not_called()
    mocks.create.assert_not_called()


def test_read_transaction_ends_before_the_cloud_probe(mocks: _EndpointMocks) -> None:
    present = _present(GRANITE)
    events = _record_calls(mocks, {False: present, True: present})
    db_session = MagicMock()
    db_session.commit.side_effect = lambda: events.append("commit")

    with pytest.raises(_GuardPassed):
        set_new_search_settings(
            _spec_request(EmbeddingProvider.COHERE, "embed-v5.0-pro"),
            _=MagicMock(),
            db_session=db_session,
        )

    assert events == ["unlocked_read", "commit", "probe", "locked_read"]


def test_cloud_probe_runs_under_lock_when_present_changed(
    mocks: _EndpointMocks,
) -> None:
    # The unlocked read sees the target as PRESENT (no probe needed), but PRESENT
    # changed before the lock, so the check under the lock still probes.
    events = _record_calls(
        mocks,
        {
            False: _present("embed-v5.0-pro", EmbeddingProvider.COHERE),
            True: _present(GRANITE),
        },
    )

    _assert_allowed(_spec_request(EmbeddingProvider.COHERE, "embed-v5.0-pro"))

    assert events == ["unlocked_read", "locked_read", "probe"]


def test_self_hosted_target_does_not_read_present_before_the_lock(
    mocks: _EndpointMocks,
) -> None:
    mocks.set_present(_present(NOMIC))

    _assert_allowed(_spec_request(None, "voyageai/voyage-4-nano"))

    assert [call.kwargs.get("for_update") for call in mocks.current.call_args_list] == [
        True
    ]


# ---- The probe itself ----


def _cloud_provider(api_key: str | None = "sk-test-key") -> MagicMock:
    provider = MagicMock()
    if api_key is None:
        provider.api_key = None
    else:
        provider.api_key.get_value.return_value = api_key
    provider.api_url = None
    provider.api_version = None
    provider.deployment_name = None
    return provider


def _fake_encode(dim: int, *, count_delta: int = 0) -> Any:
    def _encode(texts: list[str], text_type: EmbedTextType) -> list[list[float]]:  # noqa: ARG001
        return [[0.1] * dim for _ in range(len(texts) + count_delta)]

    return _encode


@patch(f"{_MODULE}.EmbeddingModel")
def test_probe_embeds_passages_and_query_with_stored_credentials(
    mock_embedding_model_class: MagicMock,
) -> None:
    embedding_model = mock_embedding_model_class.return_value
    embedding_model.encode.side_effect = _fake_encode(2048)
    provider = _cloud_provider()

    _probe_cloud_embedding_model(
        _spec_request(EmbeddingProvider.COHERE, "embed-v5.0-fast"), provider
    )

    kwargs = mock_embedding_model_class.call_args.kwargs
    assert kwargs["model_name"] == "embed-v5.0-fast"
    assert kwargs["provider_type"] == EmbeddingProvider.COHERE
    assert kwargs["api_key"] == "sk-test-key"
    assert kwargs["reduced_dimension"] is None
    provider.api_key.get_value.assert_called_once_with(apply_mask=False)

    text_types = [
        call.kwargs["text_type"] for call in embedding_model.encode.call_args_list
    ]
    assert text_types == [EmbedTextType.PASSAGE, EmbedTextType.QUERY]
    passages = embedding_model.encode.call_args_list[0].args[0]
    queries = embedding_model.encode.call_args_list[1].args[0]
    assert len(passages) == 2
    assert len(queries) == 1


@patch(f"{_MODULE}.EmbeddingModel")
def test_probe_expects_reduced_dimension(mock_embedding_model_class: MagicMock) -> None:
    embedding_model = mock_embedding_model_class.return_value
    embedding_model.encode.side_effect = _fake_encode(1024)
    request = _spec_request(
        EmbeddingProvider.OPENAI, "text-embedding-3-large", reduced_dimension=1024
    )

    _probe_cloud_embedding_model(request, _cloud_provider())

    assert mock_embedding_model_class.call_args.kwargs["reduced_dimension"] == 1024


@patch(f"{_MODULE}.EmbeddingModel")
def test_probe_rejects_wrong_vector_size(mock_embedding_model_class: MagicMock) -> None:
    mock_embedding_model_class.return_value.encode.side_effect = _fake_encode(1536)

    with pytest.raises(OnyxError) as exc:
        _probe_cloud_embedding_model(
            _spec_request(EmbeddingProvider.COHERE, "embed-v5.0-pro"),
            _cloud_provider(),
        )

    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert "size 1536" in exc.value.detail
    assert "expects size 2048" in exc.value.detail


@patch(f"{_MODULE}.EmbeddingModel")
def test_probe_rejects_wrong_vector_count(
    mock_embedding_model_class: MagicMock,
) -> None:
    mock_embedding_model_class.return_value.encode.side_effect = _fake_encode(
        2048, count_delta=-1
    )

    with pytest.raises(OnyxError) as exc:
        _probe_cloud_embedding_model(
            _spec_request(EmbeddingProvider.COHERE, "embed-v5.0-pro"),
            _cloud_provider(),
        )

    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert "returned 1 passage and 0 query vectors" in exc.value.detail


@patch(f"{_MODULE}.EmbeddingModel")
def test_probe_reports_provider_error_with_key_hint(
    mock_embedding_model_class: MagicMock,
) -> None:
    mock_embedding_model_class.return_value.encode.side_effect = RuntimeError(
        "HTTP error embedding text with cohere - Status 404: model not found"
    )

    with pytest.raises(OnyxError) as exc:
        _probe_cloud_embedding_model(
            _spec_request(EmbeddingProvider.COHERE, "embed-v5.0-pro"),
            _cloud_provider(),
        )

    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert "model not found" in exc.value.detail
    assert "'embed-v5.0-pro' (cohere)" in exc.value.detail
    assert "API key has access to this model" in exc.value.detail
    assert "Vertex AI" not in exc.value.detail


@patch(f"{_MODULE}.EmbeddingModel")
def test_probe_error_for_google_adds_region_hint(
    mock_embedding_model_class: MagicMock,
) -> None:
    mock_embedding_model_class.return_value.encode.side_effect = RuntimeError(
        "Publisher model not found in location us-central1"
    )

    with pytest.raises(OnyxError) as exc:
        _probe_cloud_embedding_model(
            _spec_request(EmbeddingProvider.GOOGLE, "gemini-embedding-2"),
            _cloud_provider('{"project_id": "p"}'),
        )

    assert "us-central1" in exc.value.detail
    assert "global, us and eu" in exc.value.detail


@patch(f"{_MODULE}.EmbeddingModel")
def test_probe_truncates_long_provider_errors(
    mock_embedding_model_class: MagicMock,
) -> None:
    mock_embedding_model_class.return_value.encode.side_effect = RuntimeError(
        "x" * 10_000
    )

    with pytest.raises(OnyxError) as exc:
        _probe_cloud_embedding_model(
            _spec_request(EmbeddingProvider.OPENAI, "text-embedding-3-small"),
            _cloud_provider(),
        )

    assert len(exc.value.detail) < 2_000
