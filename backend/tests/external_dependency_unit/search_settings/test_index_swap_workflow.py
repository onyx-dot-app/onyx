"""Workflow-level test for the INSTANT index swap.

When `check_and_perform_index_swap` runs against an `INSTANT` switchover, it
calls `delete_all_documents_for_connector_credential_pair` for each cc_pair.
This test exercises that full workflow end-to-end and asserts that the
attached `Document.file_id`s are also reaped — not just the document rows.

Mocks Vespa (`get_all_document_indices`) since this is testing the postgres +
file_store side effects of the swap, not the document index integration.
"""

from collections.abc import Generator
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.connectors.models import Document
from onyx.connectors.models import IndexAttemptMetadata
from onyx.connectors.models import InputType
from onyx.connectors.models import TextSection
from onyx.context.search.models import SavedSearchSettings
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import EmbeddingPrecision
from onyx.db.enums import SwitchoverType
from onyx.db.file_record import get_filerecord_by_file_id_optional
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import Document as DBDocument
from onyx.db.models import FileRecord
from onyx.db.models import IndexModelStatus
from onyx.db.search_settings import create_search_settings
from onyx.db.swap_index import check_and_perform_index_swap
from onyx.file_store.file_store import get_default_file_store
from onyx.indexing.indexing_pipeline import index_doc_batch_prepare


# ---------------------------------------------------------------------------
# Helpers (kept inline; extract to a shared conftest if a 4th test file shows up)
# ---------------------------------------------------------------------------


def _make_doc(doc_id: str, file_id: str | None = None) -> Document:
    return Document(
        id=doc_id,
        source=DocumentSource.MOCK_CONNECTOR,
        semantic_identifier=f"semantic-{doc_id}",
        sections=[TextSection(text="content", link=None)],
        metadata={},
        file_id=file_id,
    )


def _stage_file(content: bytes = b"raw bytes") -> str:
    return get_default_file_store().save_file(
        content=BytesIO(content),
        display_name=None,
        file_origin=FileOrigin.INDEXING_STAGING,
        file_type="application/octet-stream",
        file_metadata={"test": True},
    )


def _get_doc_row(db_session: Session, doc_id: str) -> DBDocument | None:
    db_session.expire_all()
    return db_session.query(DBDocument).filter(DBDocument.id == doc_id).one_or_none()


def _get_filerecord(db_session: Session, file_id: str) -> FileRecord | None:
    db_session.expire_all()
    return get_filerecord_by_file_id_optional(file_id=file_id, db_session=db_session)


def _make_cc_pair(db_session: Session) -> ConnectorCredentialPair:
    connector = Connector(
        name=f"test-connector-{uuid4().hex[:8]}",
        source=DocumentSource.MOCK_CONNECTOR,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={},
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
    )
    db_session.add(connector)
    db_session.flush()

    credential = Credential(
        source=DocumentSource.MOCK_CONNECTOR,
        credential_json={},
    )
    db_session.add(credential)
    db_session.flush()

    pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=f"test-cc-pair-{uuid4().hex[:8]}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
        auto_sync_options=None,
    )
    db_session.add(pair)
    db_session.commit()
    db_session.refresh(pair)
    return pair


def _make_saved_search_settings(
    *,
    switchover_type: SwitchoverType = SwitchoverType.REINDEX,
) -> SavedSearchSettings:
    return SavedSearchSettings(
        model_name=f"test-embedding-model-{uuid4().hex[:8]}",
        model_dim=768,
        normalize=True,
        query_prefix="",
        passage_prefix="",
        provider_type=None,
        index_name=f"test_index_{uuid4().hex[:8]}",
        multipass_indexing=False,
        embedding_precision=EmbeddingPrecision.FLOAT,
        reduced_dimension=None,
        enable_contextual_rag=False,
        contextual_rag_llm_name=None,
        contextual_rag_llm_provider=None,
        switchover_type=switchover_type,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
    full_deployment_setup: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    yield _make_cc_pair(db_session)


@pytest.fixture
def attempt_metadata(cc_pair: ConnectorCredentialPair) -> IndexAttemptMetadata:
    return IndexAttemptMetadata(
        connector_id=cc_pair.connector_id,
        credential_id=cc_pair.credential_id,
        attempt_id=None,
        request_id="test-request",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInstantIndexSwap:
    """`SwitchoverType.INSTANT` wipes all docs for every cc_pair as part of
    the swap. The associated raw files must be reaped too."""

    def test_instant_swap_deletes_docs_and_files(
        self,
        db_session: Session,
        attempt_metadata: IndexAttemptMetadata,
    ) -> None:
        # Index two docs with attached files via the normal pipeline.
        file_id_a = _stage_file(content=b"alpha")
        file_id_b = _stage_file(content=b"beta")
        doc_a = _make_doc(f"doc-{uuid4().hex[:8]}", file_id=file_id_a)
        doc_b = _make_doc(f"doc-{uuid4().hex[:8]}", file_id=file_id_b)

        index_doc_batch_prepare(
            documents=[doc_a, doc_b],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        # Sanity: docs and files exist before the swap.
        assert _get_doc_row(db_session, doc_a.id) is not None
        assert _get_doc_row(db_session, doc_b.id) is not None
        assert _get_filerecord(db_session, file_id_a) is not None
        assert _get_filerecord(db_session, file_id_b) is not None

        # Stage a FUTURE search settings with INSTANT switchover. The next
        # `check_and_perform_index_swap` call will see this and trigger the
        # bulk-delete path on every cc_pair.
        create_search_settings(
            search_settings=_make_saved_search_settings(
                switchover_type=SwitchoverType.INSTANT
            ),
            db_session=db_session,
            status=IndexModelStatus.FUTURE,
        )

        # Vespa is patched out — we're testing the postgres + file_store
        # side effects, not the document-index integration.
        with patch(
            "onyx.db.swap_index.get_all_document_indices",
            return_value=[],
        ):
            old_settings = check_and_perform_index_swap(db_session)

        assert old_settings is not None, "INSTANT swap should have executed"

        # Documents are gone.
        assert _get_doc_row(db_session, doc_a.id) is None
        assert _get_doc_row(db_session, doc_b.id) is None

        # Files are gone — the workflow's bulk-delete path correctly
        # propagated through to file cleanup.
        assert _get_filerecord(db_session, file_id_a) is None
        assert _get_filerecord(db_session, file_id_b) is None

    def test_instant_swap_with_mixed_docs_does_not_break(
        self,
        db_session: Session,
        attempt_metadata: IndexAttemptMetadata,
    ) -> None:
        """A mix of docs with and without file_ids must all be swept up
        without errors during the swap."""
        file_id = _stage_file()
        doc_with = _make_doc(f"doc-{uuid4().hex[:8]}", file_id=file_id)
        doc_without = _make_doc(f"doc-{uuid4().hex[:8]}", file_id=None)

        index_doc_batch_prepare(
            documents=[doc_with, doc_without],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        create_search_settings(
            search_settings=_make_saved_search_settings(
                switchover_type=SwitchoverType.INSTANT
            ),
            db_session=db_session,
            status=IndexModelStatus.FUTURE,
        )

        with patch(
            "onyx.db.swap_index.get_all_document_indices",
            return_value=[],
        ):
            old_settings = check_and_perform_index_swap(db_session)

        assert old_settings is not None

        assert _get_doc_row(db_session, doc_with.id) is None
        assert _get_doc_row(db_session, doc_without.id) is None
        assert _get_filerecord(db_session, file_id) is None
