"""Tests that search settings with contextual RAG are properly propagated
to the indexing pipeline's LLM configuration."""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.context.search.models import SavedSearchSettings
from onyx.context.search.models import SearchSettingsCreationRequest
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import EmbeddingPrecision
from onyx.db.llm import fetch_default_contextual_rag_model
from onyx.db.llm import update_default_contextual_model
from onyx.db.llm import upsert_llm_provider
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexModelStatus
from onyx.db.models import SearchSettings
from onyx.db.search_settings import create_search_settings
from onyx.db.search_settings import update_search_settings
from onyx.db.swap_index import check_and_perform_index_swap
from onyx.indexing.indexing_pipeline import IndexingPipelineResult
from onyx.indexing.indexing_pipeline import run_indexing_pipeline
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from onyx.server.manage.search_settings import set_new_search_settings
from onyx.server.manage.search_settings import update_saved_search_settings
from shared_configs.configs import PRESERVED_SEARCH_FIELDS
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_cc_pair

TEST_PROVIDER_NAME = "test-contextual-provider"
TEST_MODEL_NAME = "test-contextual-model"

UPDATED_PROVIDER_NAME = "updated-contextual-provider"
UPDATED_MODEL_NAME = "updated-contextual-model"


def _create_llm_provider_and_model(
    db_session: Session,
    provider_name: str,
    model_name: str,
) -> int:
    """Insert an LLM provider with a single visible model configuration.
    Returns the model_configuration_id of the created model."""
    provider_view = upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=provider_name,
            provider="openai",
            api_key="test-api-key",
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name=model_name,
                    is_visible=True,
                    max_input_tokens=4096,
                )
            ],
        ),
        db_session=db_session,
    )
    mc = next(
        (mc for mc in provider_view.model_configurations if mc.name == model_name),
        None,
    )
    if not mc or mc.id is None:
        raise ValueError(f"Could not find model config for {model_name}")
    return mc.id


def _make_creation_request(
    model_configuration_id: int | None = None,
    enable_contextual_rag: bool = True,
) -> SearchSettingsCreationRequest:
    return SearchSettingsCreationRequest(
        model_name="test-embedding-model",
        model_dim=768,
        normalize=True,
        query_prefix="",
        passage_prefix="",
        provider_type=None,
        index_name=None,
        multipass_indexing=False,
        embedding_precision=EmbeddingPrecision.FLOAT,
        reduced_dimension=None,
        enable_contextual_rag=enable_contextual_rag,
        contextual_rag_model_configuration_id=model_configuration_id,
    )


def _make_saved_search_settings(
    model_configuration_id: int | None = None,
    enable_contextual_rag: bool = True,
) -> SavedSearchSettings:
    return SavedSearchSettings(
        model_name="test-embedding-model",
        model_dim=768,
        normalize=True,
        query_prefix="",
        passage_prefix="",
        provider_type=None,
        index_name="test_index",
        multipass_indexing=False,
        embedding_precision=EmbeddingPrecision.FLOAT,
        reduced_dimension=None,
        enable_contextual_rag=enable_contextual_rag,
        contextual_rag_model_configuration_id=model_configuration_id,
    )


def _run_indexing_pipeline_with_mocks(
    mock_get_llm: MagicMock,
    mock_index_handler: MagicMock,
    db_session: Session,
) -> None:
    """Call run_indexing_pipeline with all heavy dependencies mocked out."""
    mock_get_llm.return_value = MagicMock()
    mock_index_handler.return_value = IndexingPipelineResult(
        new_docs=0,
        total_docs=0,
        total_chunks=0,
        failures=[],
    )

    run_indexing_pipeline(
        document_batch=[],
        request_id=None,
        embedder=MagicMock(),
        document_indices=[],
        db_session=db_session,
        tenant_id="public",
        adapter=MagicMock(),
        chunker=MagicMock(chunk_token_limit=512),
    )


@pytest.fixture()
def baseline_search_settings(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    """Ensure a baseline PRESENT search settings row exists in the DB,
    which is required before set_new_search_settings can be called."""
    baseline = _make_saved_search_settings(enable_contextual_rag=False)
    create_search_settings(
        search_settings=baseline,
        db_session=db_session,
        status=IndexModelStatus.PRESENT,
    )
    # Sync default contextual model to match PRESENT (clears any leftover state)
    update_default_contextual_model(
        db_session=db_session,
        enable_contextual_rag=baseline.enable_contextual_rag,
        model_configuration_id=None,
    )


@patch("onyx.server.manage.search_settings.get_all_document_indices")
@patch("onyx.server.manage.search_settings.get_default_document_index")
def test_port_seed_excludes_invalid_cc_pair(
    mock_get_default_doc_index: MagicMock,  # noqa: ARG001
    mock_get_all_doc_indices: MagicMock,
    baseline_search_settings: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    """The port seed loop must seed only cc_pairs the port will actually copy. An
    INVALID cc_pair (excluded by the port's indexable_statuses scope) must NOT get a
    synthetic seed — otherwise its backlog is never ported while the seed cursor
    claims "already done", so its docs vanish from the live index once it's fixed."""
    mock_get_all_doc_indices.return_value = []

    active_pair = make_cc_pair(db_session)
    invalid_pair = make_cc_pair(db_session)
    active_pair.status = ConnectorCredentialPairStatus.ACTIVE
    invalid_pair.status = ConnectorCredentialPairStatus.INVALID
    db_session.commit()

    future_id: int | None = None
    try:
        future_id = set_new_search_settings(
            search_settings_new=_make_creation_request(enable_contextual_rag=False),
            _=MagicMock(),
            db_session=db_session,
        ).id

        seeded_cc_ids = {
            row.connector_credential_pair_id
            for row in db_session.query(IndexAttempt).filter(
                IndexAttempt.search_settings_id == future_id,
                IndexAttempt.is_synthetic_seed.is_(True),
            )
        }
        assert active_pair.id in seeded_cc_ids  # portable -> seeded
        assert invalid_pair.id not in seeded_cc_ids  # not portable -> NOT seeded
    finally:
        db_session.rollback()
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id.in_(
                [active_pair.id, invalid_pair.id]
            )
        ).delete(synchronize_session="fetch")
        db_session.commit()
        if future_id is not None:
            db_session.query(SearchSettings).filter(
                SearchSettings.id == future_id
            ).delete(synchronize_session="fetch")
            db_session.commit()
        cleanup_cc_pair(db_session, active_pair)
        cleanup_cc_pair(db_session, invalid_pair)


# port-flow swap gate: no cc_pair requires porting in this test, so it swaps now
@patch(
    "onyx.db.swap_index.fetch_indexable_standard_connector_credential_pair_ids",
    new=lambda *_a, **_k: [],
)
@patch("onyx.db.swap_index.get_all_document_indices")
@patch("onyx.server.manage.search_settings.get_all_document_indices")
@patch("onyx.server.manage.search_settings.get_default_document_index")
@patch("onyx.indexing.indexing_pipeline.get_contextual_rag_llm_for_search_settings")
@patch("onyx.indexing.indexing_pipeline.index_doc_batch_with_handler")
def test_indexing_pipeline_uses_contextual_rag_settings_from_create(
    mock_index_handler: MagicMock,
    mock_get_llm: MagicMock,
    mock_get_doc_index: MagicMock,  # noqa: ARG001
    mock_get_all_doc_indices_search_settings: MagicMock,  # noqa: ARG001
    mock_get_all_doc_indices: MagicMock,
    baseline_search_settings: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    """After creating FUTURE settings and swapping to PRESENT,
    fetch_default_contextual_rag_model should match the PRESENT settings and
    run_indexing_pipeline should resolve the LLM from those PRESENT settings."""
    mc_id = _create_llm_provider_and_model(
        db_session=db_session,
        provider_name=TEST_PROVIDER_NAME,
        model_name=TEST_MODEL_NAME,
    )

    set_new_search_settings(
        search_settings_new=_make_creation_request(model_configuration_id=mc_id),
        _=MagicMock(),
        db_session=db_session,
    )

    # PRESENT still has contextual RAG disabled, so default should be None
    default_model = fetch_default_contextual_rag_model(db_session)
    assert default_model is None

    # Swap FUTURE → PRESENT. New settings use the port flow, whose swap gate waits
    # for each portable cc_pair's port; none require porting here (patched empty),
    # so the swap proceeds immediately.
    mock_get_all_doc_indices.return_value = []
    old_settings = check_and_perform_index_swap(db_session)
    assert old_settings is not None, "Swap should have occurred"

    # Now PRESENT has contextual RAG enabled, default should match
    default_model = fetch_default_contextual_rag_model(db_session)
    assert default_model is not None
    assert default_model.name == TEST_MODEL_NAME

    _run_indexing_pipeline_with_mocks(mock_get_llm, mock_index_handler, db_session)

    # now resolved from the SearchSettings object, not a bare model-config id
    mock_get_llm.assert_called_once()
    (called_settings,) = mock_get_llm.call_args.args
    assert called_settings.contextual_rag_model_configuration_id == mc_id


# port-flow swap gate: no cc_pair requires porting in this test, so it swaps now
@patch(
    "onyx.db.swap_index.fetch_indexable_standard_connector_credential_pair_ids",
    new=lambda *_a, **_k: [],
)
@patch("onyx.db.swap_index.get_all_document_indices")
@patch("onyx.server.manage.search_settings.get_all_document_indices")
@patch("onyx.server.manage.search_settings.get_default_document_index")
@patch("onyx.indexing.indexing_pipeline.get_contextual_rag_llm_for_search_settings")
@patch("onyx.indexing.indexing_pipeline.index_doc_batch_with_handler")
def test_indexing_pipeline_uses_updated_contextual_rag_settings(
    mock_index_handler: MagicMock,
    mock_get_llm: MagicMock,
    mock_get_doc_index: MagicMock,  # noqa: ARG001
    mock_get_all_doc_indices_search_settings: MagicMock,  # noqa: ARG001
    mock_get_all_doc_indices: MagicMock,
    baseline_search_settings: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    """After creating FUTURE settings, swapping to PRESENT, then updating
    via update_saved_search_settings, run_indexing_pipeline should use
    the updated model configuration ID."""
    mc_id = _create_llm_provider_and_model(
        db_session=db_session,
        provider_name=TEST_PROVIDER_NAME,
        model_name=TEST_MODEL_NAME,
    )
    updated_mc_id = _create_llm_provider_and_model(
        db_session=db_session,
        provider_name=UPDATED_PROVIDER_NAME,
        model_name=UPDATED_MODEL_NAME,
    )

    # Create FUTURE settings with contextual RAG enabled
    set_new_search_settings(
        search_settings_new=_make_creation_request(model_configuration_id=mc_id),
        _=MagicMock(),
        db_session=db_session,
    )

    # PRESENT still has contextual RAG disabled, so default should be None
    default_model = fetch_default_contextual_rag_model(db_session)
    assert default_model is None

    # Swap FUTURE → PRESENT. New settings use the port flow, whose swap gate waits
    # for each portable cc_pair's port; none require porting here (patched empty),
    # so the swap proceeds immediately.
    mock_get_all_doc_indices.return_value = []
    old_settings = check_and_perform_index_swap(db_session)
    assert old_settings is not None, "Swap should have occurred"

    # Now PRESENT has contextual RAG enabled, default should match
    default_model = fetch_default_contextual_rag_model(db_session)
    assert default_model is not None
    assert default_model.name == TEST_MODEL_NAME

    # Update the PRESENT model configuration
    update_saved_search_settings(
        search_settings=_make_saved_search_settings(
            model_configuration_id=updated_mc_id,
        ),
        _=MagicMock(),
        db_session=db_session,
    )

    default_model = fetch_default_contextual_rag_model(db_session)
    assert default_model is not None
    assert default_model.name == UPDATED_MODEL_NAME

    _run_indexing_pipeline_with_mocks(mock_get_llm, mock_index_handler, db_session)

    # resolved from the updated PRESENT SearchSettings
    mock_get_llm.assert_called_once()
    (called_settings,) = mock_get_llm.call_args.args
    assert called_settings.contextual_rag_model_configuration_id == updated_mc_id


@patch("onyx.server.manage.search_settings.get_all_document_indices")
@patch("onyx.server.manage.search_settings.get_default_document_index")
@patch("onyx.indexing.indexing_pipeline.get_contextual_rag_llm_for_search_settings")
@patch("onyx.indexing.indexing_pipeline.index_doc_batch_with_handler")
def test_indexing_pipeline_skips_llm_when_contextual_rag_disabled(
    mock_index_handler: MagicMock,
    mock_get_llm: MagicMock,
    mock_get_doc_index: MagicMock,  # noqa: ARG001
    mock_get_all_doc_indices_search_settings: MagicMock,  # noqa: ARG001
    baseline_search_settings: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    """When contextual RAG is disabled in search settings, the pipeline should not
    resolve a contextual-RAG LLM at all."""
    mc_id = _create_llm_provider_and_model(
        db_session=db_session,
        provider_name=TEST_PROVIDER_NAME,
        model_name=TEST_MODEL_NAME,
    )

    set_new_search_settings(
        search_settings_new=_make_creation_request(
            model_configuration_id=mc_id,
            enable_contextual_rag=False,
        ),
        _=MagicMock(),
        db_session=db_session,
    )

    # PRESENT has contextual RAG disabled, so default should be None
    default_model = fetch_default_contextual_rag_model(db_session)
    assert default_model is None

    _run_indexing_pipeline_with_mocks(mock_get_llm, mock_index_handler, db_session)

    mock_get_llm.assert_not_called()


def test_create_search_settings_coerces_none_prefixes(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    """Registry-less cloud providers (e.g. Bedrock/LiteLLM/Azure) can arrive
    without query/passage prefixes. The search_settings DB columns are NOT
    NULL, so create_search_settings must coerce None -> "" instead of raising
    a NotNullViolation. Regression test for the v4.0.x embedding-switch bug."""
    saved = _make_saved_search_settings(enable_contextual_rag=False)
    # Explicitly force the None path the failing customer hit.
    saved.query_prefix = None
    saved.passage_prefix = None

    created = create_search_settings(
        search_settings=saved,
        db_session=db_session,
        status=IndexModelStatus.FUTURE,
    )

    assert created.query_prefix == ""
    assert created.passage_prefix == ""


def test_update_search_settings_coerces_none_prefixes(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    """The update path setattr's columns straight from model_dump(). Today's
    callers always include the prefixes in PRESERVED_SEARCH_FIELDS, but if a
    caller does NOT preserve them, an explicit null must still not write NULL to
    the NOT NULL columns. Exercises the coercion with prefixes un-preserved
    (while keeping 'id' preserved so the PK isn't nulled)."""
    current = create_search_settings(
        search_settings=_make_saved_search_settings(enable_contextual_rag=False),
        db_session=db_session,
        status=IndexModelStatus.PRESENT,
    )

    updated = _make_saved_search_settings(enable_contextual_rag=False)
    updated.query_prefix = None
    updated.passage_prefix = None

    preserved = [
        f
        for f in PRESERVED_SEARCH_FIELDS
        if f not in ("query_prefix", "passage_prefix")
    ]
    update_search_settings(current, updated, preserved_fields=preserved)
    db_session.commit()

    assert current.query_prefix == ""
    assert current.passage_prefix == ""


def test_creation_request_defaults_blank_prefixes() -> None:
    """When the client omits query/passage prefixes entirely, the Pydantic
    request model should default them to "" rather than leaving them unset/None."""
    request = SearchSettingsCreationRequest(
        model_name="bedrock-titan-embed-text-2",
        model_dim=1024,
        normalize=False,
        provider_type=None,
        index_name=None,
        multipass_indexing=False,
        embedding_precision=EmbeddingPrecision.FLOAT,
        reduced_dimension=None,
        enable_contextual_rag=False,
        contextual_rag_model_configuration_id=None,
    )

    assert request.query_prefix == ""
    assert request.passage_prefix == ""
