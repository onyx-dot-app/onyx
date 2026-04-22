"""End-to-end test for docfetching orphan-file cleanup.

Two cleanup seams are covered:

    Start-of-run sweep (`reap_prior_attempt_staged_files`):
        run 1: a mock connector stages a raw file via raw_file_callback,
               then crashes — docfetching re-raises without reaping,
               because promotion happens in a separate docprocessing pod
               and the files may still be in-flight.
        run 2: the same cc_pair's next attempt starts up, and the
               start-of-run sweep detects the orphan from run 1 and
               reaps it.

    Attempt-end cleanup (`cleanup_staged_files_for_attempt`):
        Exercised directly. Called from `check_indexing_completion` in
        docprocessing once every batch has been processed — at that point
        any file still INDEXING_STAGING for the attempt is a real drop
        (connector emitted no Document, or the Document was filtered as
        stale by `index_doc_batch_prepare`).

Runs against real Postgres + real file store because the sweep's query
depends on JSONB metadata filtering and the file_store client is what
actually deletes blob + FileRecord together.
"""

from collections.abc import Generator
from collections.abc import Iterator
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.background.indexing.run_docfetching import run_docfetching_entrypoint
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.connectors import factory as connector_factory
from onyx.connectors.factory import instantiate_connector
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import InputType
from onyx.connectors.models import TextSection
from onyx.db.enums import EmbeddingPrecision
from onyx.db.enums import IndexingStatus
from onyx.db.enums import IndexModelStatus
from onyx.db.file_record import get_filerecord_by_file_id_optional
from onyx.db.models import Credential
from onyx.db.models import FileRecord
from onyx.db.models import IndexAttempt
from onyx.db.models import SearchSettings
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.staging import build_raw_file_callback
from onyx.file_store.staging import cleanup_staged_files_for_attempt
from onyx.file_store.staging import reap_prior_attempt_staged_files
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_cc_pair


# ---------------------------------------------------------------------------
# Mock connector that stages a file, yields a doc, then crashes
# ---------------------------------------------------------------------------


class MockCrashingConnector(LoadConnector):
    """LoadConnector that stages one raw file via `raw_file_callback`,
    yields a Document referencing it, then raises `RuntimeError` on the
    NEXT iteration — simulating a worker crash mid-batch after the file
    has already hit the file_store.

    Two instantiation paths, one class:
    - Direct construction (`MockCrashingConnector(payload=..., doc_id=...,
      raise_after_first=...)`) for the narrow helper tests.
    - Empty-kwargs construction via `instantiate_connector` for the
      full-factory test; the test then sets `payload` / `doc_id` /
      `raise_after_first` as attributes before running.
    """

    def __init__(
        self,
        payload: bytes = b"",
        doc_id: str = "",
        raise_after_first: bool = False,
        **_ignored: Any,
    ) -> None:
        self.payload = payload
        self.doc_id = doc_id
        self.raise_after_first = raise_after_first
        # Populated when the generator runs. Tests assert on this.
        self.staged_file_id: str | None = None

    def load_credentials(
        self, credentials: dict[str, Any]  # noqa: ARG002
    ) -> dict[str, Any] | None:
        return None

    def load_from_state(self) -> Iterator[list[Document | HierarchyNode]]:
        assert (
            self.raw_file_callback is not None
        ), "Test harness must wire up raw_file_callback"
        file_id = self.raw_file_callback(
            BytesIO(self.payload), "application/octet-stream"
        )
        self.staged_file_id = file_id
        yield [
            Document(
                id=self.doc_id,
                source=DocumentSource.MOCK_CONNECTOR,
                semantic_identifier=f"sem-{self.doc_id}",
                sections=[TextSection(text="payload", link=None)],
                metadata={},
                file_id=file_id,
            )
        ]
        if self.raise_after_first:
            raise RuntimeError("simulated connector crash mid-batch")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_staging_files_for_attempt(attempt_id: int, db_session: Session) -> int:
    db_session.expire_all()
    return (
        db_session.query(FileRecord)
        .filter(FileRecord.file_origin == FileOrigin.INDEXING_STAGING)
        .filter(
            FileRecord.file_metadata["index_attempt_id"].as_string() == str(attempt_id)
        )
        .count()
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tenant_and_cc_pair_ids(
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
) -> tuple[str, int]:
    """Identifiers the raw_file_callback's metadata is scoped by.

    `cc_pair_id` doesn't need to correspond to a real `ConnectorCredentialPair`
    row — the orphan cleanup hooks read metadata via JSONB, not via FK. A
    synthetic id is sufficient and avoids seeding a full cc_pair just to
    satisfy schema constraints the test doesn't exercise.
    """
    from tests.external_dependency_unit.constants import TEST_TENANT_ID

    return TEST_TENANT_ID, abs(hash(uuid4().hex)) % 10_000_000


@pytest.fixture
def file_cleanup(
    db_session: Session,  # noqa: ARG001 — keeps tenant context alive
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
) -> Generator[list[str], None, None]:
    """Reap any file_ids the test touched, regardless of pass/fail.

    Lets teardown clean up even when the assertions under test fail — the
    point of the test is that the cleanup hook removes orphans, so we
    can't rely on the hook alone to tidy up between failing runs.
    """
    created: list[str] = []
    try:
        yield created
    finally:
        store = get_default_file_store()
        for fid in created:
            try:
                store.delete_file(fid, error_on_missing=False)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_one_crashes_after_staging_then_run_two_cleans_up(
    db_session: Session,
    tenant_and_cc_pair_ids: tuple[str, int],
    file_cleanup: list[str],
) -> None:
    """Primary scenario. Run 1: connector stages a file, crashes before
    any `finally` could run. Run 2: start-of-run sweep reaps the orphan."""
    tenant_id, cc_pair_id = tenant_and_cc_pair_ids

    # === Run 1: stage a file, then crash before cleanup can fire ===
    run_1_attempt_id = 1001
    callback_1 = build_raw_file_callback(
        index_attempt_id=run_1_attempt_id,
        cc_pair_id=cc_pair_id,
        tenant_id=tenant_id,
    )
    connector = MockCrashingConnector(
        payload=b"run 1 bytes",
        doc_id=f"doc-{uuid4().hex[:8]}",
        raise_after_first=True,
    )
    connector.set_raw_file_callback(callback_1)

    # Simulate a HARD crash: exhaust the generator without any try/finally
    # around it — modeling an OOM kill or pod eviction where the attempt-
    # end cleanup never gets a chance to run.
    with pytest.raises(RuntimeError, match="simulated connector crash"):
        for _ in connector.load_from_state():
            pass

    assert connector.staged_file_id is not None
    file_cleanup.append(connector.staged_file_id)

    # Pre-check: the staged file exists with STAGING origin.
    record = get_filerecord_by_file_id_optional(
        file_id=connector.staged_file_id, db_session=db_session
    )
    assert record is not None
    assert record.file_origin == FileOrigin.INDEXING_STAGING
    # The JSONB metadata carrying attempt_id is verified implicitly by the
    # sweep below: if it weren't tagged correctly, the metadata-filtered
    # query inside `reap_prior_attempt_staged_files` wouldn't match.

    # === Run 2: start-of-run sweep runs before any fetching ===
    run_2_attempt_id = 1002
    reaped = reap_prior_attempt_staged_files(
        current_attempt_id=run_2_attempt_id,
        cc_pair_id=cc_pair_id,
        tenant_id=tenant_id,
        db_session=db_session,
    )

    # The orphan from run 1 is gone — blob + FileRecord both deleted.
    assert reaped == 1
    assert (
        get_filerecord_by_file_id_optional(
            file_id=connector.staged_file_id, db_session=db_session
        )
        is None
    )


def test_attempt_end_cleanup_wipes_staged_files(
    db_session: Session,
    tenant_and_cc_pair_ids: tuple[str, int],
    file_cleanup: list[str],
) -> None:
    """Attempt-end cleanup path: connector stages and raises, then the
    attempt-completion hook (in production, `check_indexing_completion`)
    invokes `cleanup_staged_files_for_attempt` and wipes the orphan.

    Distinguishes the attempt-end cleanup from the attempt-start sweep —
    here we never get to run 2, because the completion hook handles it.
    """
    tenant_id, cc_pair_id = tenant_and_cc_pair_ids

    attempt_id = 2001
    callback = build_raw_file_callback(
        index_attempt_id=attempt_id,
        cc_pair_id=cc_pair_id,
        tenant_id=tenant_id,
    )
    connector = MockCrashingConnector(
        payload=b"will be reaped by finally",
        doc_id=f"doc-{uuid4().hex[:8]}",
        raise_after_first=True,
    )
    connector.set_raw_file_callback(callback)

    with pytest.raises(RuntimeError, match="simulated connector crash"):
        for _ in connector.load_from_state():
            pass

    assert connector.staged_file_id is not None
    file_cleanup.append(connector.staged_file_id)

    # Simulate the completion-path cleanup (what `check_indexing_completion`
    # calls once every docprocessing batch has finished).
    cleanup_staged_files_for_attempt(index_attempt_id=attempt_id, db_session=db_session)

    assert (
        get_filerecord_by_file_id_optional(
            file_id=connector.staged_file_id, db_session=db_session
        )
        is None
    )


def test_run_two_sweep_does_not_touch_current_attempts_files(
    db_session: Session,
    tenant_and_cc_pair_ids: tuple[str, int],
    file_cleanup: list[str],
) -> None:
    """Safety: when the start-of-run sweep fires for attempt 2, it must
    not touch STAGING files tagged with attempt 2's own id. Otherwise a
    retry's own in-flight fetches would get swept out from under it."""
    tenant_id, cc_pair_id = tenant_and_cc_pair_ids

    # Stage a file under the CURRENT attempt id — as if the fetch had
    # already produced a file before the sweep ran (out of order, but the
    # filter needs to handle it correctly regardless).
    current_attempt = 3001
    callback = build_raw_file_callback(
        index_attempt_id=current_attempt,
        cc_pair_id=cc_pair_id,
        tenant_id=tenant_id,
    )
    file_id = callback(BytesIO(b"my own file"), "application/octet-stream")
    file_cleanup.append(file_id)

    reaped = reap_prior_attempt_staged_files(
        current_attempt_id=current_attempt,
        cc_pair_id=cc_pair_id,
        tenant_id=tenant_id,
        db_session=db_session,
    )

    assert reaped == 0
    assert (
        get_filerecord_by_file_id_optional(file_id=file_id, db_session=db_session)
        is not None
    )


def test_run_two_sweep_scoped_to_cc_pair(
    db_session: Session,
    tenant_and_cc_pair_ids: tuple[str, int],
    file_cleanup: list[str],
) -> None:
    """Safety: the sweep must not touch STAGING files belonging to OTHER
    cc_pairs, even if they share a tenant and a (coincidentally matching)
    attempt_id."""
    tenant_id, cc_pair_id = tenant_and_cc_pair_ids
    other_cc_pair_id = cc_pair_id + 1

    # Orphan under THIS cc_pair (should be swept).
    own_callback = build_raw_file_callback(
        index_attempt_id=4001,
        cc_pair_id=cc_pair_id,
        tenant_id=tenant_id,
    )
    own_file_id = own_callback(BytesIO(b"mine"), "application/octet-stream")
    file_cleanup.append(own_file_id)

    # File under ANOTHER cc_pair (must survive).
    other_callback = build_raw_file_callback(
        index_attempt_id=4001,
        cc_pair_id=other_cc_pair_id,
        tenant_id=tenant_id,
    )
    other_file_id = other_callback(
        BytesIO(b"someone else's"), "application/octet-stream"
    )
    file_cleanup.append(other_file_id)

    reap_prior_attempt_staged_files(
        current_attempt_id=4002,
        cc_pair_id=cc_pair_id,
        tenant_id=tenant_id,
        db_session=db_session,
    )

    assert (
        get_filerecord_by_file_id_optional(file_id=own_file_id, db_session=db_session)
        is None
    )
    # Other cc_pair's file must still exist.
    assert (
        get_filerecord_by_file_id_optional(file_id=other_file_id, db_session=db_session)
        is not None
    )


def test_real_factory_path_with_injected_mock_connector(
    db_session: Session,
    tenant_and_cc_pair_ids: tuple[str, int],
    file_cleanup: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full factory-path exercise: the real `instantiate_connector` resolves
    our mock via `_connector_cache`, wires the `raw_file_callback` via
    `set_raw_file_callback`, and returns a ready-to-run connector. We drive
    it, let it crash, and then invoke the attempt-end cleanup directly
    (standing in for `check_indexing_completion`'s completion-path call).

    What this proves over the direct-construction tests:
    - Injection into the production factory works — a mock connector can be
      dropped in place of any real source via `_connector_cache`.
    - `set_raw_file_callback` is called by the factory at the right point
      (after `load_credentials`), so the staging metadata flows through.
    - The complete path — factory → connector.run → callback → file_store →
      exception → cleanup — reaps the orphan.

    This uses the real factory module but stays below the `run_docfetching_entrypoint`
    seam (no IndexAttempt / SearchSettings / Celery app / DocumentBatchStorage
    needed) because everything those dependencies touch is orthogonal to the
    orphan-cleanup behavior.
    """
    tenant_id, cc_pair_id = tenant_and_cc_pair_ids

    # Register the mock against `DocumentSource.MOCK_CONNECTOR`. The factory's
    # `_load_connector_class` checks this cache first, so the CONNECTOR_CLASS_MAP
    # lookup never runs. `monkeypatch.setitem` restores the previous value
    # (likely absent → KeyError → falls back to the map on next call) after
    # the test.
    monkeypatch.setitem(
        connector_factory._connector_cache,
        DocumentSource.MOCK_CONNECTOR,
        MockCrashingConnector,
    )

    # Seed the minimum Credential row the factory needs. `credential_json={}`
    # materializes as a SensitiveValue wrapper once loaded via `expire` +
    # re-fetch, which is what the factory calls `.get_value` on.
    credential = Credential(
        source=DocumentSource.MOCK_CONNECTOR,
        credential_json={},
    )
    db_session.add(credential)
    db_session.commit()
    db_session.expire(credential)

    attempt_id = 6001
    callback = build_raw_file_callback(
        index_attempt_id=attempt_id,
        cc_pair_id=cc_pair_id,
        tenant_id=tenant_id,
    )

    # Real factory call — resolves the mock via the cache, wires the callback.
    connector = instantiate_connector(
        db_session=db_session,
        source=DocumentSource.MOCK_CONNECTOR,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={},
        credential=credential,
        raw_file_callback=callback,
    )
    assert isinstance(connector, MockCrashingConnector)
    assert connector.raw_file_callback is callback

    # Configure the mock after instantiation (the factory called __init__
    # with empty kwargs, using the defaults).
    connector.payload = b"factory-path payload"
    connector.doc_id = f"doc-{uuid4().hex[:8]}"
    connector.raise_after_first = True

    # Drive the connector, let it crash, then run the completion-path
    # cleanup directly.
    with pytest.raises(RuntimeError, match="simulated connector crash"):
        for _ in connector.load_from_state():
            pass

    assert connector.staged_file_id is not None
    file_cleanup.append(connector.staged_file_id)

    cleanup_staged_files_for_attempt(index_attempt_id=attempt_id, db_session=db_session)

    # Attempt-end cleanup wiped the staged file, even though the connector
    # raised after the callback fired.
    assert (
        get_filerecord_by_file_id_optional(
            file_id=connector.staged_file_id, db_session=db_session
        )
        is None
    )

    # Clean up the seeded Credential.
    db_session.delete(credential)
    db_session.commit()


def test_run_docfetching_entrypoint_leaves_crash_orphans_for_next_sweep(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full-pipeline test: call the actual `run_docfetching_entrypoint`.

    The only things we swap out are:
    - The connector class (via `_connector_cache` injection) so the mock
      gets resolved for `DocumentSource.MOCK_CONNECTOR`.
    - The Celery app (MagicMock) — `connector_document_extraction` calls
      `app.send_task(...)` per batch, but our connector raises before any
      batch completes so this is never actually exercised.

    Everything else is production code: `transition_attempt_to_in_progress`,
    the real factory, the real ConnectorRunner, the real file_store, and
    `connector_document_extraction`'s DocumentBatchStorage setup.

    The mock stages a file via the real raw_file_callback, then raises.
    The entrypoint deliberately does NOT reap on crash — attempt-end
    cleanup lives in docprocessing's `check_indexing_completion`, not
    here, because docprocessing runs in a separate pod and may still be
    promoting files. Instead, the orphan survives and is picked up by
    the next attempt's start-of-run sweep.
    """
    # Subclass of the mock connector so we can (a) preset the crash config
    # at construction time — the factory calls `connector_class(**{})`, so
    # we don't get to pass args — and (b) peek at the instance afterward.
    # `_get_connector_runner` keeps the instance internal to the
    # ConnectorRunner it returns, so we need this side channel.
    doc_id = f"doc-{uuid4().hex[:8]}"
    created_instances: list[MockCrashingConnector] = []

    class _TrackingMock(MockCrashingConnector):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.payload = b"entrypoint-path bytes"
            self.doc_id = doc_id
            self.raise_after_first = True
            created_instances.append(self)

    # Register against `DocumentSource.MOCK_CONNECTOR`. `_load_connector_class`
    # checks this cache first, so our class wins over the normal mapping.
    monkeypatch.setitem(
        connector_factory._connector_cache,
        DocumentSource.MOCK_CONNECTOR,
        _TrackingMock,
    )

    # --- Seed the minimum DB state run_docfetching_entrypoint needs ---
    cc_pair = make_cc_pair(db_session)
    try:
        search_settings = SearchSettings(
            model_name="test-model",
            model_dim=768,
            normalize=True,
            query_prefix="",
            passage_prefix="",
            status=IndexModelStatus.PRESENT,
            index_name=f"test_index_{uuid4().hex[:8]}",
            embedding_precision=EmbeddingPrecision.FLOAT,
        )
        db_session.add(search_settings)
        db_session.commit()
        db_session.refresh(search_settings)

        index_attempt = IndexAttempt(
            connector_credential_pair_id=cc_pair.id,
            search_settings_id=search_settings.id,
            from_beginning=False,
            status=IndexingStatus.NOT_STARTED,
            celery_task_id=f"test-task-{uuid4().hex[:8]}",
        )
        db_session.add(index_attempt)
        db_session.commit()
        db_session.refresh(index_attempt)
        attempt_id = index_attempt.id
        search_settings_id = search_settings.id

        # Call the real entrypoint. The mock connector raises after
        # staging; the entrypoint's `try/finally` must run the cleanup
        # before re-raising.
        mock_app = MagicMock()
        with pytest.raises(RuntimeError, match="simulated connector crash"):
            run_docfetching_entrypoint(
                app=mock_app,
                index_attempt_id=attempt_id,
                tenant_id=TEST_TENANT_ID,
                connector_credential_pair_id=cc_pair.id,
            )

        # The factory created exactly one connector instance and the real
        # raw_file_callback flowed into it — confirm a file was staged.
        assert len(created_instances) == 1
        staged_file_id = created_instances[0].staged_file_id
        assert staged_file_id is not None, (
            "Mock connector never staged a file; "
            "raw_file_callback wiring likely broken."
        )

        # Entrypoint no longer reaps on crash — the file must still exist.
        # Any cleanup now happens via the completion path in docprocessing
        # or the next attempt's start-of-run sweep.
        record = get_filerecord_by_file_id_optional(
            file_id=staged_file_id, db_session=db_session
        )
        assert record is not None, (
            "Staged file was unexpectedly reaped by the entrypoint; "
            "attempt-end cleanup should live in check_indexing_completion."
        )
        assert record.file_origin == FileOrigin.INDEXING_STAGING

        # Now simulate the next attempt starting up — the start-of-run
        # sweep should reap the orphan from the crashed attempt.
        reaped = reap_prior_attempt_staged_files(
            current_attempt_id=attempt_id + 1,
            cc_pair_id=cc_pair.id,
            tenant_id=TEST_TENANT_ID,
            db_session=db_session,
        )
        assert reaped == 1
        assert (
            get_filerecord_by_file_id_optional(
                file_id=staged_file_id, db_session=db_session
            )
            is None
        )

    finally:
        # Clean up seeded rows in FK-safe order: attempt → settings → cc_pair.
        db_session.query(IndexAttempt).filter(IndexAttempt.id == attempt_id).delete(
            synchronize_session="fetch"
        )
        db_session.query(SearchSettings).filter(
            SearchSettings.id == search_settings_id
        ).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, cc_pair)


def test_attempt_end_cleanup_leaves_promoted_files_alone(
    db_session: Session,
    tenant_and_cc_pair_ids: tuple[str, int],
    file_cleanup: list[str],
) -> None:
    """Attempt-end cleanup targets `INDEXING_STAGING` only. A file that
    was already promoted to `CONNECTOR` must survive the sweep — it's
    referenced by a committed Document and is no longer an orphan."""
    tenant_id, cc_pair_id = tenant_and_cc_pair_ids

    attempt_id = 5001
    callback = build_raw_file_callback(
        index_attempt_id=attempt_id,
        cc_pair_id=cc_pair_id,
        tenant_id=tenant_id,
    )

    # File 1: staged but not promoted → should be reaped.
    orphan_id = callback(BytesIO(b"orphan"), "application/octet-stream")
    file_cleanup.append(orphan_id)

    # File 2: staged and manually promoted → should survive.
    promoted_id = callback(BytesIO(b"survivor"), "application/octet-stream")
    file_cleanup.append(promoted_id)
    db_session.query(FileRecord).filter(FileRecord.file_id == promoted_id).update(
        {FileRecord.file_origin: FileOrigin.CONNECTOR}
    )
    db_session.commit()

    assert _count_staging_files_for_attempt(attempt_id, db_session) == 1

    reaped = cleanup_staged_files_for_attempt(
        index_attempt_id=attempt_id, db_session=db_session
    )

    assert reaped == 1
    assert (
        get_filerecord_by_file_id_optional(file_id=orphan_id, db_session=db_session)
        is None
    )
    # Promoted file untouched.
    survivor = get_filerecord_by_file_id_optional(
        file_id=promoted_id, db_session=db_session
    )
    assert survivor is not None
    assert survivor.file_origin == FileOrigin.CONNECTOR
