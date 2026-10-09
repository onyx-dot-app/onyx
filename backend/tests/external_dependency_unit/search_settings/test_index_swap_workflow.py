"""Workflow-level tests for the INSTANT index swap.

When `check_and_perform_index_swap` runs against an `INSTANT` switchover, it
calls `delete_all_documents_for_connector_credential_pair` for each cc_pair.
This test exercises that full workflow end-to-end and asserts that the
attached `Document.file_id`s are also reaped — not just the document rows.
`TestSwapVisibility` checks what other sessions read while a swap commits.

Mocks the document index (`get_default_document_index`) since this is testing
the postgres + file_store side effects of the swap, not the document index
integration.
"""

from collections.abc import Generator
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from onyx.connectors.models import IndexAttemptMetadata
from onyx.context.search.models import SavedSearchSettings
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import SwitchoverType
from onyx.db.models import ConnectorCredentialPair, IndexModelStatus, SearchSettings
from onyx.db.port_orphan_candidate import port_target_settings_id
from onyx.db.search_settings import (
    create_search_settings,
    get_active_search_settings,
    get_current_search_settings,
    get_search_settings_by_id,
)
from onyx.db.swap_index import _perform_index_swap, check_and_perform_index_swap
from onyx.indexing.indexing_pipeline import index_doc_batch_prepare
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    get_doc_row,
    get_filerecord,
    make_cc_pair,
    make_doc,
    make_instant_port_future,
    stage_file,
    undo_index_swap,
)

# ---------------------------------------------------------------------------
# Helpers (file-local)
# ---------------------------------------------------------------------------


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
    pair = make_cc_pair(db_session)
    try:
        yield pair
    finally:
        cleanup_cc_pair(db_session, pair)


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
        file_id_a = stage_file(content=b"alpha")
        file_id_b = stage_file(content=b"beta")
        doc_a = make_doc(f"doc-{uuid4().hex[:8]}", file_id=file_id_a)
        doc_b = make_doc(f"doc-{uuid4().hex[:8]}", file_id=file_id_b)

        index_doc_batch_prepare(
            documents=[doc_a, doc_b],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        # Sanity: docs and files exist before the swap.
        assert get_doc_row(db_session, doc_a.id) is not None
        assert get_doc_row(db_session, doc_b.id) is not None
        assert get_filerecord(db_session, file_id_a) is not None
        assert get_filerecord(db_session, file_id_b) is not None

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

        # The document index is patched out — we're testing the postgres +
        # file_store side effects, not the document-index integration.
        with patch("onyx.db.swap_index.get_default_document_index"):
            old_settings = check_and_perform_index_swap(db_session)

        assert old_settings is not None, "INSTANT swap should have executed"

        # Documents are gone.
        assert get_doc_row(db_session, doc_a.id) is None
        assert get_doc_row(db_session, doc_b.id) is None

        # Files are gone — the workflow's bulk-delete path correctly
        # propagated through to file cleanup.
        assert get_filerecord(db_session, file_id_a) is None
        assert get_filerecord(db_session, file_id_b) is None

    def test_instant_swap_with_mixed_docs_does_not_break(
        self,
        db_session: Session,
        attempt_metadata: IndexAttemptMetadata,
    ) -> None:
        """A mix of docs with and without file_ids must all be swept up
        without errors during the swap."""
        file_id = stage_file()
        doc_with = make_doc(f"doc-{uuid4().hex[:8]}", file_id=file_id)
        doc_without = make_doc(f"doc-{uuid4().hex[:8]}", file_id=None)

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

        with patch("onyx.db.swap_index.get_default_document_index"):
            old_settings = check_and_perform_index_swap(db_session)

        assert old_settings is not None

        assert get_doc_row(db_session, doc_with.id) is None
        assert get_doc_row(db_session, doc_without.id) is None
        assert get_filerecord(db_session, file_id) is None


@pytest.fixture
def instant_port_future(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[int, SearchSettings], None, None]:
    """The live PRESENT id and an INSTANT port-flow FUTURE. Teardown makes the
    original row PRESENT again and deletes the FUTURE."""
    present_id = get_current_search_settings(db_session).id
    future = make_instant_port_future(db_session)
    future_id = future.id
    try:
        yield present_id, future
    finally:
        undo_index_swap(db_session, present_id, future_id)
        db_session.query(SearchSettings).filter(SearchSettings.id == future_id).delete(
            synchronize_session="fetch"
        )
        db_session.commit()


class TestSwapVisibility:
    """At each commit of a swap, other sessions see exactly one of the two swapped
    rows as PRESENT, and after it one consistent PRESENT/FUTURE pair. A port
    attempt that starts during an INSTANT swap reads these rows."""

    def test_swap_never_commits_without_a_present_row(
        self,
        db_session: Session,
        instant_port_future: tuple[int, SearchSettings],
    ) -> None:
        present_id, future = instant_port_future
        present_rows_per_commit: list[int] = []

        def _count_present_rows(_session: Session) -> None:
            # Count only the two swapped rows: other tests can leave PRESENT rows.
            with get_session_with_current_tenant() as reader:
                present_rows_per_commit.append(
                    reader.scalar(
                        select(func.count())
                        .select_from(SearchSettings)
                        .where(
                            SearchSettings.id.in_([present_id, future.id]),
                            SearchSettings.status == IndexModelStatus.PRESENT,
                        )
                    )
                    or 0
                )

        event.listen(db_session, "after_commit", _count_present_rows)
        try:
            with patch("onyx.db.swap_index.get_default_document_index"):
                assert (
                    _perform_index_swap(db_session, future, all_cc_pairs=[]) is not None
                )
        finally:
            event.remove(db_session, "after_commit", _count_present_rows)

        assert present_rows_per_commit
        assert all(count == 1 for count in present_rows_per_commit)

    def test_active_settings_refresh_a_row_loaded_before_the_swap(
        self,
        db_session: Session,
        instant_port_future: tuple[int, SearchSettings],
    ) -> None:
        present_id, future = instant_port_future
        with get_session_with_current_tenant() as port_session:
            # A starting port attempt loads its FUTURE row, then the swap commits.
            loaded = get_search_settings_by_id(port_session, future.id)
            assert loaded is not None
            assert loaded.status == IndexModelStatus.FUTURE

            with patch("onyx.db.swap_index.get_default_document_index"):
                assert (
                    _perform_index_swap(db_session, future, all_cc_pairs=[]) is not None
                )

            active = get_active_search_settings(port_session)
            assert active.primary.id == future.id
            assert active.primary.port_backfill_source_id == present_id
            assert active.secondary is None
            # The attempt is still the port target, so it does not cancel itself.
            assert (
                port_target_settings_id(active.primary, active.secondary) == future.id
            )
