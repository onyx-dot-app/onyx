"""Upgrade-only guard in set_new_search_settings: a new embedding target must be the
PRESENT model (same-model re-index) or a selectable registry model. Legacy registry
models are refused; custom self-hosted models, LiteLLM and Azure stay open. Bifrost
and selectable cloud targets are probed before the PRESENT row lock."""

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
from onyx.natural_language_processing.embedding_auth import VertexEmbeddingAuth
from onyx.server.manage.search_settings import (
    _check_embedding_model_target,
    _validate_cloud_embedding_model,
    set_new_search_settings,
)
from shared_configs.configs import DEFAULT_DOCUMENT_ENCODER_MODEL
from shared_configs.embedding_models import (
    EmbeddingModelSpec,
    find_embedding_model_spec,
    selectable_embedding_model_specs,
)
from shared_configs.enums import EmbeddingProvider
from shared_configs.utils import clean_model_name

_MODULE = "onyx.server.manage.search_settings"

NOMIC = "nomic-ai/nomic-embed-text-v1"
E5 = "intfloat/e5-base-v2"
GRANITE = DEFAULT_DOCUMENT_ENCODER_MODEL
VOYAGE_NANO = "voyageai/voyage-4-nano"
NEMOTRON = "nvidia/Nemotron-3-Embed-1B-BF16"
COHERE = EmbeddingProvider.COHERE
GOOGLE = EmbeddingProvider.GOOGLE
OPENAI = EmbeddingProvider.OPENAI


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
    *,
    sent_name: str | None = None,
    **overrides: Any,
) -> SearchSettingsCreationRequest:
    """A request with the registry's settings for the model, as the UI sends it.
    sent_name replaces the model name in the request (e.g. a case variant)."""
    spec = find_embedding_model_spec(provider_type, model_name)
    assert spec is not None
    values: dict[str, Any] = {
        "provider_type": spec.provider_type,
        "model_dim": spec.model_dim,
        "normalize": spec.normalize,
        "query_prefix": spec.query_prefix,
        "passage_prefix": spec.passage_prefix,
    }
    values.update(overrides)
    return _request(sent_name or model_name, **values)


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


# ---- The rules ----

_ALLOWED = [
    pytest.param(
        _present(NOMIC), _request(NOMIC), False, id="same-legacy-model-empty-prefixes"
    ),
    pytest.param(
        _present(E5), _request("IntFloat/E5_Base.V2"), False, id="same-model-variant"
    ),
    pytest.param(
        _present(VOYAGE_NANO, model_dim=1024),
        _request(VOYAGE_NANO, model_dim=1024),
        False,
        id="same-model-keeps-a-custom-dim",
    ),
    pytest.param(
        _present(VOYAGE_NANO, model_dim=1024),
        _spec_request(None, VOYAGE_NANO),
        False,
        id="same-model-moves-to-the-registry-dim",
    ),
    pytest.param(
        _present("embed-english-v3.0", COHERE),
        _request("embed-english-v3.0", provider_type=COHERE, model_dim=1024),
        False,
        id="same-legacy-cloud-model",
    ),
    pytest.param(
        _present(NOMIC, reduced_dimension=256),
        _request(NOMIC, reduced_dimension=256),
        False,
        id="same-self-hosted-model-keeps-a-stored-reduced-dimension",
    ),
    pytest.param(
        _present("text-embedding-3-large", OPENAI, reduced_dimension=1024),
        _spec_request(OPENAI, "text-embedding-3-large", reduced_dimension=1024),
        True,
        id="same-model-keeps-reduced-dimension-in-multi-tenant",
    ),
    pytest.param(
        _present(NOMIC),
        _spec_request(None, GRANITE, query_prefix=None, passage_prefix=None),
        False,
        id="selectable-with-null-prefixes",
    ),
    pytest.param(
        _present(NOMIC),
        _spec_request(OPENAI, "text-embedding-3-large", reduced_dimension=1024),
        False,
        id="selectable-with-reduced-dimension",
    ),
    pytest.param(
        _present(GRANITE),
        _request("my-org/custom-embedder", model_dim=1024),
        False,
        id="custom-self-hosted-model",
    ),
    pytest.param(
        _present(GRANITE),
        _request(
            "embed-english-v3.0", provider_type=EmbeddingProvider.LITELLM, model_dim=123
        ),
        False,
        id="litellm-with-a-legacy-looking-name",
    ),
    pytest.param(
        _present(GRANITE),
        _request(
            "text-embedding-3-large",
            provider_type=EmbeddingProvider.AZURE,
            model_dim=123,
        ),
        False,
        id="azure",
    ),
]

_REJECTED = [
    pytest.param(
        _present(GRANITE),
        _request(GRANITE, model_dim=768),
        False,
        "must keep its dimension",
        id="same-model-with-another-dim",
    ),
    pytest.param(
        _present("text-embedding-3-large", OPENAI),
        _spec_request(OPENAI, "text-embedding-3-large", reduced_dimension=1024),
        True,
        "share its index",
        id="same-model-changes-reduced-dimension-in-multi-tenant",
    ),
    pytest.param(
        _present(GRANITE),
        _spec_request(None, GRANITE, reduced_dimension=256),
        False,
        "do not support reduced_dimension",
        id="same-self-hosted-model-adds-reduced-dimension",
    ),
    pytest.param(
        _present(GRANITE),
        _request("my-org/custom-embedder", model_dim=1024, reduced_dimension=256),
        False,
        "do not support reduced_dimension",
        id="custom-self-hosted-model-with-reduced-dimension",
    ),
    pytest.param(
        _present("embed-english-v3.0"),
        _request("embed-english-v3.0", provider_type=COHERE, model_dim=1024),
        False,
        "legacy embedding model",
        id="same-name-but-another-provider",
    ),
    pytest.param(
        _present(NOMIC),
        _spec_request(None, GRANITE, model_dim=768),
        False,
        "model_dim must be 384",
        id="selectable-with-another-dim",
    ),
    pytest.param(
        _present(NOMIC),
        _spec_request(None, GRANITE, normalize=False),
        False,
        "normalize must be True",
        id="selectable-with-another-normalize",
    ),
    pytest.param(
        _present(NOMIC),
        _spec_request(None, NEMOTRON, query_prefix="query:"),
        False,
        "query_prefix must be 'query: '",
        id="selectable-prefix-without-its-trailing-space",
    ),
    pytest.param(
        _present(NOMIC),
        _spec_request(OPENAI, "text-embedding-3-large", reduced_dimension=0),
        False,
        "between 1 and 3071",
        id="reduced-dimension-zero",
    ),
    pytest.param(
        _present(NOMIC),
        _spec_request(OPENAI, "text-embedding-3-large", reduced_dimension=3072),
        False,
        "between 1 and 3071",
        id="reduced-dimension-full-size",
    ),
    pytest.param(
        _present(NOMIC),
        _spec_request(COHERE, "embed-v5.0-pro", reduced_dimension=256),
        False,
        "does not support reduced_dimension",
        id="reduced-dimension-without-support",
    ),
    pytest.param(
        _present("embed-english-v3.0", COHERE),
        _spec_request(OPENAI, "text-embedding-3-large", reduced_dimension=1024),
        True,
        "not supported in Onyx Cloud",
        id="reduced-dimension-in-multi-tenant",
    ),
    pytest.param(
        _present(GRANITE),
        _spec_request(None, NOMIC),
        False,
        "legacy embedding model",
        id="legacy-self-hosted-model",
    ),
    pytest.param(
        _present(GRANITE),
        _request(" nomic_ai/Nomic.Embed.Text.V1 "),
        False,
        "legacy embedding model",
        id="legacy-self-hosted-name-variant",
    ),
    pytest.param(
        _present(GRANITE),
        _spec_request(GOOGLE, "text-embedding-005"),
        False,
        "legacy embedding model",
        id="legacy-cloud-model",
    ),
    pytest.param(
        _present(GRANITE),
        _request("text-embedding-ada-002", provider_type=OPENAI),
        False,
        "not an embedding model that Onyx supports",
        id="unknown-model-of-a-registry-provider",
    ),
]


@pytest.mark.parametrize(("present", "target", "multi_tenant"), _ALLOWED)
def test_allowed_target(
    present: MagicMock, target: SearchSettingsCreationRequest, multi_tenant: bool
) -> None:
    with patch(f"{_MODULE}.MULTI_TENANT", multi_tenant):
        _check_embedding_model_target(target, present)


@pytest.mark.parametrize(("present", "target", "multi_tenant", "problem"), _REJECTED)
def test_rejected_target(
    present: MagicMock,
    target: SearchSettingsCreationRequest,
    multi_tenant: bool,
    problem: str,
) -> None:
    with (
        patch(f"{_MODULE}.MULTI_TENANT", multi_tenant),
        pytest.raises(OnyxError) as exc,
    ):
        _check_embedding_model_target(target, present)

    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert problem in exc.value.detail


@pytest.mark.parametrize(
    "spec", selectable_embedding_model_specs(), ids=lambda spec: spec.model_name
)
def test_every_selectable_model_is_allowed_with_registry_settings(
    spec: EmbeddingModelSpec,
) -> None:
    _check_embedding_model_target(
        _spec_request(spec.provider_type, spec.model_name), _present(NOMIC)
    )


def test_rejection_names_the_selectable_models() -> None:
    with pytest.raises(OnyxError) as exc:
        _check_embedding_model_target(_spec_request(None, NOMIC), _present(GRANITE))

    for spec in selectable_embedding_model_specs():
        assert spec.model_name in exc.value.detail


# ---- Wiring in set_new_search_settings ----


class _GuardPassed(Exception):
    """Patched into create_search_settings to prove the guards let the request through."""


@dataclass
class _EndpointMocks:
    provider: MagicMock
    current: MagicMock
    create: MagicMock
    probe: MagicMock

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
        patch(f"{_MODULE}.get_secondary_search_settings", return_value=None),
        patch(f"{_MODULE}.port_backfill_has_pending_work", return_value=False),
        patch(f"{_MODULE}._guard_index_name_reuse"),
        patch(f"{_MODULE}.compute_wont_port_cc_pair_ids", return_value=[]),
        patch(f"{_MODULE}.set_reclaim_intent_on_current__no_commit"),
        patch(f"{_MODULE}.create_search_settings", side_effect=_GuardPassed) as create,
        patch(f"{_MODULE}._validate_cloud_embedding_model") as probe,
    ):
        yield _EndpointMocks(
            provider=provider, current=current, create=create, probe=probe
        )


def _submit(
    target: SearchSettingsCreationRequest, db_session: MagicMock | None = None
) -> None:
    set_new_search_settings(target, _=MagicMock(), db_session=db_session or MagicMock())


def test_selectable_cloud_target_is_probed_before_the_present_lock(
    mocks: _EndpointMocks,
) -> None:
    events: list[str] = []

    def _locked_read(*_args: object, **_kwargs: object) -> MagicMock:
        events.append("locked_read")
        return _present(GRANITE)

    mocks.current.side_effect = _locked_read
    mocks.probe.side_effect = lambda *_args: events.append("probe")
    db_session = MagicMock()
    db_session.commit.side_effect = lambda: events.append("commit")

    with pytest.raises(_GuardPassed):
        _submit(
            _spec_request(COHERE, "embed-v5.0-pro", sent_name="Embed-V5.0-Pro"),
            db_session,
        )

    # The read transaction ends before the network call; nothing is locked yet.
    assert events == ["commit", "probe", "locked_read"]
    probed_request, probed_provider = mocks.probe.call_args.args
    assert probed_request.model_name == "embed-v5.0-pro"
    assert probed_provider is mocks.provider.return_value
    assert mocks.created_settings().model_name == "embed-v5.0-pro"


@pytest.mark.parametrize(
    ("present", "target", "stored_name"),
    [
        pytest.param(
            _present(NOMIC),
            _spec_request(
                None,
                GRANITE,
                sent_name="  IBM-Granite/Granite-Embedding-97M-Multilingual-R2 ",
            ),
            GRANITE,
            id="new-target",
        ),
        pytest.param(
            _present(VOYAGE_NANO),
            _spec_request(None, VOYAGE_NANO, sent_name="VoyageAI/Voyage-4-Nano"),
            VOYAGE_NANO,
            id="same-model-reindex",
        ),
    ],
)
def test_selectable_target_is_stored_with_its_canonical_name(
    mocks: _EndpointMocks,
    present: MagicMock,
    target: SearchSettingsCreationRequest,
    stored_name: str,
) -> None:
    """The model server and the tokenizer match registry names exactly. A variant
    would load without the pinned revision and the model's fix-ups."""
    mocks.current.return_value = present

    with pytest.raises(_GuardPassed):
        _submit(target)

    created = mocks.created_settings()
    assert created.model_name == stored_name
    assert created.index_name is not None
    assert created.index_name.startswith(
        f"danswer_chunk_{clean_model_name(stored_name)}"
    )
    mocks.probe.assert_not_called()


def test_rejected_target_creates_nothing(mocks: _EndpointMocks) -> None:
    mocks.current.return_value = _present(GRANITE)

    with pytest.raises(OnyxError) as exc:
        _submit(_spec_request(COHERE, "embed-english-v3.0"))

    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    # Only Bifrost and selectable cloud targets are probed.
    mocks.probe.assert_not_called()
    mocks.create.assert_not_called()


def test_cloud_probe_failure_blocks_the_reindex(mocks: _EndpointMocks) -> None:
    mocks.probe.side_effect = OnyxError(OnyxErrorCode.VALIDATION_ERROR, "no access")

    with pytest.raises(OnyxError) as exc:
        _submit(_spec_request(GOOGLE, "gemini-embedding-2"))

    assert exc.value.detail == "no access"
    mocks.create.assert_not_called()
    mocks.current.assert_not_called()


def test_cloud_probe_uses_the_stored_vertex_config() -> None:
    """A Workload Identity provider has no service account JSON, so the probe
    needs the stored vertex_config to authenticate."""
    provider = MagicMock()
    provider.provider_type = EmbeddingProvider.GOOGLE
    provider.api_key = None
    provider.api_url = None
    provider.api_version = None
    provider.deployment_name = None
    provider.vertex_config = {
        "auth_method": "workload_identity",
        "project_id": "target-project",
        "location": "us",
    }

    with patch(f"{_MODULE}.probe_embedding_dimension", return_value=3072) as probe:
        _validate_cloud_embedding_model(
            _spec_request(GOOGLE, "gemini-embedding-2"), provider
        )

    auth = probe.call_args.kwargs["auth"]
    assert isinstance(auth, VertexEmbeddingAuth)
    assert auth.config.auth_method == "workload_identity"
    assert auth.config.project_id == "target-project"
    assert probe.call_args.kwargs["model_name"] == "gemini-embedding-2"
