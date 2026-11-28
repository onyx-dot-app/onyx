"""The per-person pick against Postgres: who sees which question, by the same
access rules as search. No models or search index are involved; asking for
runs is turned off, so nothing is sent to Celery.

A public connector holds a handbook and a hidden document, a perm-synced
Salesforce connector holds a record only Alice may read, and Alice uploaded a
file. The pool also keeps a question about a document that is gone."""

from collections.abc import Generator
from contextlib import ExitStack, suppress
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import (
    KV_SUGGESTED_QUESTIONS_POOL_KEY,
    KV_SUGGESTED_QUESTIONS_USER_KEY,
    DocumentSource,
)
from onyx.db.document import upsert_document_by_connector_credential_pair
from onyx.db.enums import AccessType, UserFileStatus
from onyx.db.models import Document as DbDocument
from onyx.db.models import UserFile
from onyx.db.suggested_questions import get_visible_document_ids
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.features.suggested_questions import ranking
from onyx.server.features.suggested_questions.models import (
    PoolQuestion,
    QuestionKind,
    QuestionPool,
)
from onyx.server.features.suggested_questions.store import (
    save_pool,
    save_private_questions,
)
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


def _question(document_id: str, kind: QuestionKind, now: datetime) -> PoolQuestion:
    return PoolQuestion(
        id=f"q-{document_id}",
        text=f"About {document_id}?",
        kind=kind,
        document_id=document_id,
        source_type=DocumentSource.GOOGLE_DRIVE,
        search_position=0,
        best_for=None,
        created_at=now,
    )


def _clear_kv(*keys: str) -> None:
    for key in keys:
        # Only a missing value is fine; any other error must stop the test.
        with suppress(KvKeyNotFoundError):
            get_kv_store().delete(key)


@pytest.fixture
def company(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
    make_test_user: MakeTestUser,
) -> Generator[dict[str, Any], None, None]:
    now = datetime.now(UTC)
    suffix = uuid4().hex[:8]
    ids = {
        name: f"sq-pick-{name}-{suffix}"
        for name in ("handbook", "hidden", "alice-record", "gone")
    }
    # make_test_user deletes the people and the uploads they own afterwards.
    alice = make_test_user("sq_alice")
    bob = make_test_user("sq_bob")
    upload_id = uuid4()
    # Each cleanup is registered as soon as its resource exists, so a setup
    # that fails part way still cleans up. They run in reverse order.
    with ExitStack() as cleanup:
        cleanup.callback(
            _clear_kv,
            KV_SUGGESTED_QUESTIONS_POOL_KEY,
            *(KV_SUGGESTED_QUESTIONS_USER_KEY.format(u.id) for u in (alice, bob)),
        )
        public = make_cc_pair(db_session)
        cleanup.callback(cleanup_cc_pair, db_session, public)
        synced = make_cc_pair(db_session, DocumentSource.SALESFORCE)
        cleanup.callback(cleanup_cc_pair, db_session, synced)
        # Runs first: a failed setup step leaves the session to roll back.
        cleanup.callback(db_session.rollback)

        synced.access_type = AccessType.SYNC
        db_session.add_all(
            [
                DbDocument(id=ids["handbook"], semantic_id="handbook", last_synced=now),
                DbDocument(
                    id=ids["hidden"], semantic_id="hidden", last_synced=now, hidden=True
                ),
                DbDocument(
                    id=ids["alice-record"],
                    semantic_id="alice-record",
                    last_synced=now,
                    external_user_emails=[alice.email],
                ),
                UserFile(
                    id=upload_id,
                    user_id=alice.id,
                    file_id=f"sq-pick-{suffix}",
                    name="q3-plan.txt",
                    file_type="text/plain",
                    status=UserFileStatus.COMPLETED,
                ),
            ]
        )
        db_session.commit()
        upsert_document_by_connector_credential_pair(
            db_session,
            public.connector_id,
            public.credential_id,
            [ids["handbook"], ids["hidden"]],
        )
        upsert_document_by_connector_credential_pair(
            db_session, synced.connector_id, synced.credential_id, [ids["alice-record"]]
        )
        db_session.commit()

        doc = QuestionKind.DOCUMENT
        save_pool(
            QuestionPool(
                questions=[
                    _question(ids[name], doc, now)
                    for name in ("handbook", "hidden", "gone")
                ]
            )
        )
        save_private_questions(
            alice.id,
            [
                _question(str(upload_id), QuestionKind.USER_FILE, now),
                _question(ids["alice-record"], doc, now),
            ],
            {str(upload_id), ids["alice-record"]},
            now,
        )
        yield {
            "ids": ids,
            "upload_id": str(upload_id),
            "alice": alice,
            "bob": bob,
            "now": now,
        }


@pytest.fixture
def on_the_playground(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ranking, "is_enabled", lambda: True)
    monkeypatch.setattr(ranking, "_request_run", lambda *_a, **_kw: False)
    # Without EE nothing is censored; pin it so the test does not depend on EE.
    monkeypatch.setattr(ranking, "get_censoring_enabled_sources", set)


@pytest.mark.usefixtures("on_the_playground")
def test_each_person_sees_only_the_questions_they_may_open(
    company: dict[str, Any], db_session: Session
) -> None:
    ids = company["ids"]

    def shown(person_key: str) -> dict[str, bool]:
        result = ranking.get_suggestions(
            db_session,
            company[person_key],
            get_current_tenant_id(),
            seed=1,
            poll=False,
            now=company["now"],
        )
        return {q.id: q.private for q in result.questions}

    # Not the hidden document, and not the one that is gone.
    assert shown("alice") == {
        f"q-{company['upload_id']}": True,
        f"q-{ids['alice-record']}": True,
        f"q-{ids['handbook']}": False,
    }
    assert shown("bob") == {f"q-{ids['handbook']}": False}


def test_read_time_censored_documents_are_not_visible(
    company: dict[str, Any], db_session: Session
) -> None:
    alice, record = company["alice"], company["ids"]["alice-record"]

    def visible(censored: set[DocumentSource]) -> set[str]:
        return get_visible_document_ids(db_session, alice, [], [record], censored)

    assert visible(set()) == {record}
    assert visible({DocumentSource.SALESFORCE}) == set()
    # Another person's upload is never visible.
    assert (
        get_visible_document_ids(
            db_session, company["bob"], [], [company["upload_id"]], set()
        )
        == set()
    )
