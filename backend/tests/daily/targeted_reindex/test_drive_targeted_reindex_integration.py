"""Integration coverage for targeted-reindex against real Google Drive.

Exercises the task body, connector instantiation, `Resolver.reindex`
invocation against the real Drive API, indexing pipeline run,
OpenSearch write, and resolution tracking on `IndexAttemptError` —
using the same Drive service account that the existing connector daily
tests run under.

Not full end-to-end: HTTP API + celery dispatch + FE polling are not
exercised here. `run_targeted_reindex` is invoked directly. A separate
e2e test that goes through the API endpoint and the celery worker can
land later if the integration coverage proves insufficient.

Three scenarios:
1. real existing Drive doc → resolves cleanly, error closes, doc lands
2. nonexistent Drive doc → resolution stays open, still_failing > 0
3. mixed batch (real + fake) → only the real one resolves

Connector-level reindex coverage already lives in
`tests/daily/connectors/google_drive/test_resolver.py`; this file is
the feature-level companion.
"""

import json
import os

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docprocessing.targeted_reindex_task import (
    run_targeted_reindex,
)
from onyx.db.enums import IndexingStatus
from onyx.db.models import Document as DBDocument
from onyx.db.models import IndexAttemptError
from onyx.db.targeted_reindex import create_targeted_reindex_job
from onyx.db.targeted_reindex import get_targeted_reindex_job
from onyx.db.targeted_reindex import resolve_error_ids_to_targets
from tests.daily.targeted_reindex.helpers import cleanup_targeted_reindex_state
from tests.daily.targeted_reindex.helpers import make_drive_cc_pair
from tests.daily.targeted_reindex.helpers import make_failed_index_attempt
from tests.daily.targeted_reindex.helpers import make_index_attempt_error
from tests.utils.secret_names import TestSecret

_DRIVE_ID_MAPPING_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "connectors",
    "google_drive",
    "drive_id_mapping.json",
)


def _web_view_link_for(file_id: int) -> str:
    """Resolve a stable Drive test-doc reference into the web view link
    that the resolver consumes as `failed_document.document_id`."""
    with open(_DRIVE_ID_MAPPING_PATH) as f:
        mapping: dict[str, str] = json.load(f)
    return mapping[str(file_id)]


def _run(job_id: int) -> None:
    """Invoke the task body synchronously, bypassing celery binding."""
    run_targeted_reindex(
        targeted_reindex_job_id=job_id, celery_task_id="daily-integration"
    )


@pytest.mark.secrets(TestSecret.GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR)
def test_targeted_reindex_resolves_real_drive_doc(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_secrets: dict[TestSecret, str],
) -> None:
    """Happy path: error references a real Drive doc, reindex re-fetches,
    pipeline writes, error closes, summary populates, doc row exists."""
    cc_pair = make_drive_cc_pair(
        db_session,
        test_secrets[TestSecret.GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR],
    )
    try:
        target_link = _web_view_link_for(0)
        parent = make_failed_index_attempt(db_session, cc_pair)
        err = make_index_attempt_error(
            db_session,
            parent,
            document_id=target_link,
            failure_message="synthetic 403 boom",
        )

        derived, skipped = resolve_error_ids_to_targets(db_session, [err.id])
        assert skipped == 0
        result = create_targeted_reindex_job(
            db_session=db_session,
            requested_by_user_id=None,
            targets=derived,
        )

        _run(result.targeted_reindex_job_id)

        db_session.expire_all()
        err_after = db_session.get(IndexAttemptError, err.id)
        assert err_after is not None
        assert err_after.is_resolved is True

        job = get_targeted_reindex_job(db_session, result.targeted_reindex_job_id)
        assert job is not None
        assert job.status == IndexingStatus.SUCCESS
        assert job.resolved_count == 1
        assert job.still_failing_count == 0
        assert len(job.resolved_summary) == 1
        assert job.resolved_summary[0]["id"] == err.id

        # Document row exists, signaling the pipeline reached the upsert
        # stage. We don't assert on chunks directly — that's covered by
        # the indexing pipeline's own tests.
        doc_row = (
            db_session.query(DBDocument).filter(DBDocument.id == target_link).first()
        )
        assert doc_row is not None
    finally:
        cleanup_targeted_reindex_state(db_session, cc_pair)


@pytest.mark.secrets(TestSecret.GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR)
def test_targeted_reindex_marks_still_failing_for_nonexistent_doc(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_secrets: dict[TestSecret, str],
) -> None:
    """Resolution gate: an error pointing at a nonexistent Drive doc
    must not auto-resolve. The doc never lands, so the error stays open
    and still_failing_count goes up by one."""
    cc_pair = make_drive_cc_pair(
        db_session,
        test_secrets[TestSecret.GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR],
    )
    try:
        bogus_link = "https://drive.google.com/file/d/0doesnotexist00000000000000000000"
        parent = make_failed_index_attempt(db_session, cc_pair)
        err = make_index_attempt_error(
            db_session,
            parent,
            document_id=bogus_link,
            failure_message="synthetic 404 boom",
        )

        derived, _ = resolve_error_ids_to_targets(db_session, [err.id])
        result = create_targeted_reindex_job(
            db_session=db_session,
            requested_by_user_id=None,
            targets=derived,
        )

        _run(result.targeted_reindex_job_id)

        db_session.expire_all()
        err_after = db_session.get(IndexAttemptError, err.id)
        assert err_after is not None
        assert err_after.is_resolved is False

        job = get_targeted_reindex_job(db_session, result.targeted_reindex_job_id)
        assert job is not None
        assert job.status == IndexingStatus.SUCCESS
        assert job.resolved_count == 0
        assert job.still_failing_count == 1
        assert job.resolved_summary == []

        # No DB document row should have been written for the bogus link.
        doc_row = (
            db_session.query(DBDocument).filter(DBDocument.id == bogus_link).first()
        )
        assert doc_row is None
    finally:
        cleanup_targeted_reindex_state(db_session, cc_pair)


@pytest.mark.secrets(TestSecret.GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR)
def test_targeted_reindex_mixed_real_and_fake(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_secrets: dict[TestSecret, str],
) -> None:
    """Mixed batch: one real doc, one fake. The real one closes its
    error; the fake one stays open. Counters reflect both buckets."""
    cc_pair = make_drive_cc_pair(
        db_session,
        test_secrets[TestSecret.GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR],
    )
    try:
        real_link = _web_view_link_for(2)
        fake_link = "https://drive.google.com/file/d/0fakefakefakefakefakefakefakefakea"

        parent = make_failed_index_attempt(db_session, cc_pair)
        real_err = make_index_attempt_error(
            db_session, parent, document_id=real_link, failure_message="real boom"
        )
        fake_err = make_index_attempt_error(
            db_session, parent, document_id=fake_link, failure_message="fake boom"
        )

        derived, _ = resolve_error_ids_to_targets(
            db_session, [real_err.id, fake_err.id]
        )
        assert len(derived) == 2

        result = create_targeted_reindex_job(
            db_session=db_session,
            requested_by_user_id=None,
            targets=derived,
        )

        _run(result.targeted_reindex_job_id)

        db_session.expire_all()
        real_after = db_session.get(IndexAttemptError, real_err.id)
        fake_after = db_session.get(IndexAttemptError, fake_err.id)
        assert real_after is not None and real_after.is_resolved is True
        assert fake_after is not None and fake_after.is_resolved is False

        job = get_targeted_reindex_job(db_session, result.targeted_reindex_job_id)
        assert job is not None
        assert job.status == IndexingStatus.SUCCESS
        assert job.resolved_count == 1
        assert job.still_failing_count == 1
        # Only the real doc made it to summary.
        assert len(job.resolved_summary) == 1
        assert job.resolved_summary[0]["id"] == real_err.id
    finally:
        cleanup_targeted_reindex_state(db_session, cc_pair)
