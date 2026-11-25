"""The set-based Postgres writes of a docprocessing batch: document tags."""

import random
import threading
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Document, Document__Tag, Tag
from onyx.db.tag import upsert_document_tags_batch
from onyx.db.tag_models import DocumentTagInput

_SOURCE = DocumentSource.FILE
_Metadata = dict[str, str | list[str]]


@pytest.fixture
def run_id(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[str, None, None]:
    """A prefix for the document ids and tag keys of one test. Removes them."""
    prefix = f"batch_db_writes_{uuid4().hex[:8]}_"
    yield prefix
    db_session.rollback()
    db_session.execute(
        delete(Document__Tag).where(Document__Tag.document_id.startswith(prefix))
    )
    db_session.execute(delete(Document).where(Document.id.startswith(prefix)))
    db_session.execute(delete(Tag).where(Tag.tag_key.startswith(prefix)))
    db_session.commit()


def _create_documents(db_session: Session, document_ids: list[str]) -> None:
    for document_id in document_ids:
        db_session.add(
            Document(
                id=document_id,
                semantic_id=f"semantic_{document_id}",
                boost=0,
                hidden=False,
                from_ingestion_api=False,
            )
        )
    db_session.commit()


def _upsert(batch: dict[str, _Metadata]) -> None:
    with get_session_with_current_tenant() as session:
        upsert_document_tags_batch(
            [
                DocumentTagInput(
                    document_id=document_id, source=_SOURCE, metadata=metadata
                )
                for document_id, metadata in batch.items()
            ],
            session,
        )


def _stored_tags(
    db_session: Session, prefix: str
) -> set[tuple[str, str, str, DocumentSource, bool]]:
    db_session.rollback()
    rows = db_session.execute(
        select(
            Document__Tag.document_id,
            Tag.tag_key,
            Tag.tag_value,
            Tag.source,
            Tag.is_list,
        )
        .join(Tag, Tag.id == Document__Tag.tag_id)
        .where(Document__Tag.document_id.startswith(prefix))
    )
    return {(row[0], row[1], row[2], row[3], row[4]) for row in rows}


def _expected_tags(
    batch: dict[str, _Metadata],
) -> set[tuple[str, str, str, DocumentSource, bool]]:
    expected: set[tuple[str, str, str, DocumentSource, bool]] = set()
    for document_id, metadata in batch.items():
        for key, value in metadata.items():
            if isinstance(value, list):
                expected.update(
                    (document_id, key, item, _SOURCE, True)
                    for item in value
                    if len(key) + len(item) <= 255
                )
            elif len(key) + len(value) <= 255:
                expected.add((document_id, key, value, _SOURCE, False))
    return expected


def test_tag_batch_sets_replaces_and_removes(db_session: Session, run_id: str) -> None:
    doc_a, doc_b, doc_c = (f"{run_id}{name}" for name in "abc")
    _create_documents(db_session, [doc_a, doc_b, doc_c])
    team, labels, note = f"{run_id}team", f"{run_id}labels", f"{run_id}note"

    first: dict[str, _Metadata] = {
        doc_a: {team: "red", labels: ["x", "y", "x"]},
        doc_b: {team: "red", labels: ["y"], note: "n" * 300},
        doc_c: {team: "blue", labels: []},
    }
    _upsert(first)
    assert _stored_tags(db_session, run_id) == _expected_tags(first)
    # The value that is too long makes no tag.
    assert db_session.scalars(select(Tag.id).where(Tag.tag_key == note)).all() == []

    # The same value as a single tag and as a list tag gives two tags.
    second: dict[str, _Metadata] = {
        doc_a: {team: "blue", labels: ["y", "z"]},
        doc_b: {labels: "y"},
        doc_c: {},
    }
    _upsert(second)
    assert _stored_tags(db_session, run_id) == _expected_tags(second)

    # No change writes nothing new and keeps the rows.
    _upsert(second)
    assert _stored_tags(db_session, run_id) == _expected_tags(second)

    tag_keys = db_session.execute(
        select(Tag.tag_key, Tag.tag_value, Tag.source, Tag.is_list).where(
            Tag.tag_key.startswith(run_id)
        )
    ).all()
    assert len(tag_keys) == len(set(tag_keys))


def test_tag_batch_missing_document_raises(db_session: Session, run_id: str) -> None:
    doc_a = f"{run_id}a"
    _create_documents(db_session, [doc_a])
    key = f"{run_id}team"

    with pytest.raises(ValueError, match="Invalid Document"):
        _upsert({doc_a: {key: "red"}, f"{run_id}missing": {key: "blue"}})

    assert _stored_tags(db_session, run_id) == set()


def test_tag_batch_concurrent_batches_share_tags_and_documents(
    db_session: Session, run_id: str
) -> None:
    """Batches in different document orders, with the same new tags and with
    removals, must not deadlock, fail on a unique key or lose a row."""
    document_ids = [f"{run_id}{i}" for i in range(20)]
    _create_documents(db_session, document_ids)
    keys = [f"{run_id}k{i}" for i in range(4)]

    def metadata(rng: random.Random) -> _Metadata:
        result: _Metadata = {}
        for key in rng.sample(keys, rng.randint(0, len(keys))):
            if rng.random() < 0.5:
                result[key] = f"v{rng.randint(0, 5)}"
            else:
                result[key] = [f"v{rng.randint(0, 5)}" for _ in range(3)]
        return result

    def worker(seed: int) -> None:
        rng = random.Random(seed)
        for _ in range(25):
            shuffled = rng.sample(document_ids, rng.randint(5, len(document_ids)))
            _upsert({document_id: metadata(rng) for document_id in shuffled})

    with ThreadPoolExecutor(max_workers=8) as executor:
        for future in [executor.submit(worker, seed) for seed in range(8)]:
            future.result()

    rng = random.Random(99)
    final = {document_id: metadata(rng) for document_id in document_ids}
    _upsert(final)
    assert _stored_tags(db_session, run_id) == _expected_tags(final)


def _wait_until_blocked_on_a_lock(db_session: Session, document_id: str) -> None:
    """Returns when a statement that names the document waits for a row lock."""
    blocked = text(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE wait_event_type = 'Lock' AND pid <> pg_backend_pid() "
        "AND strpos(query, :document_id) > 0"
    )
    for _ in range(200):
        db_session.rollback()
        if db_session.execute(blocked, {"document_id": document_id}).scalar_one():
            return
        db_session.execute(text("SELECT pg_sleep(0.05)"))
    raise AssertionError("The batch did not reach the lock wait.")


def test_tag_batch_does_not_deadlock_with_document_deletion(
    db_session: Session, run_id: str
) -> None:
    """Document deletion removes the tag links, then the document row. A batch
    that waits for a link must not hold a lock on the document row."""
    doc = f"{run_id}a"
    key = f"{run_id}team"
    _create_documents(db_session, [doc])
    _upsert({doc: {key: "old"}})

    errors: list[BaseException] = []

    def run_batch() -> None:
        try:
            _upsert({doc: {key: "new"}})
        except BaseException as e:
            errors.append(e)

    batch = threading.Thread(target=run_batch)
    with get_session_with_current_tenant() as deletion:
        deletion.execute(delete(Document__Tag).where(Document__Tag.document_id == doc))
        batch.start()
        try:
            _wait_until_blocked_on_a_lock(db_session, doc)
            deletion.execute(delete(Document).where(Document.id == doc))
            deletion.commit()
        except IntegrityError as e:
            errors.append(e)
        finally:
            deletion.rollback()
            batch.join()

    # One side can lose on the foreign key. A deadlock is an OperationalError.
    for error in errors:
        assert isinstance(error, IntegrityError), error
