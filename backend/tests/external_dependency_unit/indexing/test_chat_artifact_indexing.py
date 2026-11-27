"""Indexing published files (chat artifacts) against Postgres, the file
store and OpenSearch, with in-process embeddings and the Celery task functions
called directly: the newest version replaces the older one, the indexing state on the
artifact row, the beat, the re-flags at an embedding model swap and an
email change, and the artifact operations that change or delete an indexed
artifact."""

from collections.abc import Generator, Sequence
from datetime import timedelta
from unittest.mock import MagicMock, PropertyMock, patch
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue
from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from onyx.access.utils import prefix_user_email
from onyx.background.celery.tasks.chat_artifact_indexing import tasks
from onyx.background.celery.tasks.chat_artifact_indexing.tasks import (
    check_for_chat_artifact_indexing,
    process_single_chat_artifact,
)
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import (
    CELERY_USER_FILE_PROCESSING_TASK_EXPIRES,
    CHAT_ARTIFACT_INDEX_MAX_ATTEMPTS,
    DEFAULT_PERSONA_ID,
    DocumentSource,
    FileOrigin,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
from onyx.context.search.models import IndexFilters, InferenceChunk
from onyx.db import chat as chat_db
from onyx.db.chat import (
    delete_all_chat_sessions_for_user,
    delete_chat_artifact,
    delete_chat_artifact_files,
    delete_chat_session,
    delete_unpublished_chat_artifacts,
    flag_chat_artifacts_for_reindex__no_commit,
    save_chat_artifact,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ChatArtifactIndexStatus
from onyx.db.models import ChatArtifact, ChatSession, FileRecord, User
from onyx.db.search_settings import get_current_search_settings
from onyx.db.users import reconcile_user_email__no_commit
from onyx.document_index.factory import build_opensearch_document_index
from onyx.document_index.interfaces import DocumentSectionRequest
from onyx.file_store import utils as file_store_utils
from onyx.file_store.constants import ARTIFACT_TEXT_FILE_PREFIX
from onyx.file_store.file_store import (
    FILE_SIZE_MISSING_SENTINEL,
    get_default_file_store,
)
from onyx.file_store.models import ArtifactText
from onyx.indexing.chat_artifact_index import (
    chat_artifact_queued_key,
    delete_chat_artifacts_from_index,
)
from onyx.llm.cancellation import CancellationSignal
from onyx.tools.tool_implementations.sandbox import artifact_operations
from onyx.tools.tool_implementations.sandbox.models import (
    ArtifactAtPath,
    LibraryReplaceLibraryFileArguments,
    ManageLibraryArguments,
    PublishedFile,
    artifact_url,
)
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.conftest import MakeTestUser

pytestmark = pytest.mark.usefixtures(
    "tenant_context",
    "initialize_file_store",
    "full_deployment_setup",
    "fake_embeddings",
)

_TENANT = POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE


@pytest.fixture
def owner(make_test_user: MakeTestUser) -> User:
    return make_test_user("artifact_index_owner")


@pytest.fixture
def indexed_artifacts() -> Generator[list[UUID], None, None]:
    """Artifacts whose documents the test removes from the index at the end."""
    artifact_ids: list[UUID] = []
    yield artifact_ids
    delete_chat_artifacts_from_index(artifact_ids)


def _chat(db_session: Session, user: User) -> ChatSession:
    chat = ChatSession(id=uuid4(), user_id=user.id, persona_id=DEFAULT_PERSONA_ID)
    db_session.add(chat)
    db_session.commit()
    return chat


def _publish(
    chat: ChatSession,
    content: bytes,
    name: str = "report.md",
    title: str | None = None,
) -> PublishedFile:
    return save_chat_artifact(
        content,
        name=name,
        mime_type="text/markdown",
        target=ArtifactAtPath(
            chat_session_id=chat.id,
            path=f"/workspace/{name}",
        ),
        title=title,
        thumbnail=None,
        preview_pdf=None,
    )


def _artifact_id(file: PublishedFile) -> UUID:
    if file.artifact_id is None:
        raise RuntimeError("save_chat_artifact always sets the artifact")
    return file.artifact_id


def _index(artifact_id: UUID) -> None:
    process_single_chat_artifact.run(
        artifact_id=str(artifact_id),  # ty: ignore[invalid-argument-type]
        tenant_id=_TENANT,  # ty: ignore[invalid-argument-type]
    )


def _artifact(db_session: Session, artifact_id: UUID) -> ChatArtifact:
    db_session.expire_all()
    return db_session.get_one(ChatArtifact, artifact_id)


def _chunks(
    db_session: Session, artifact_id: UUID, *, acl_email: str | None = None
) -> list[InferenceChunk]:
    """The document's chunks in the PRESENT index, after a refresh; with
    `acl_email`, only those whose ACL holds that email."""
    document_index = build_opensearch_document_index(
        get_current_search_settings(db_session)
    )
    document_index.get_documents_with_any_chunk([str(artifact_id)])
    return document_index.id_based_retrieval(
        chunk_requests=[DocumentSectionRequest(document_id=str(artifact_id))],
        filters=IndexFilters(
            access_control_list=(
                None if acl_email is None else [prefix_user_email(acl_email)]
            )
        ),
    )


def _delete_chat(db_session: Session, chat: ChatSession) -> None:
    """Soft-delete the chat as the chat delete routes do; its artifacts have
    no document yet."""
    delete_chat_session(chat.user_id, chat.id, db_session, hard_delete=False)


def test_the_newest_version_replaces_the_older_one(
    db_session: Session, owner: User, indexed_artifacts: list[UUID]
) -> None:
    chat = _chat(db_session, owner)
    first = _publish(chat, b"# Plan\n\nThe zebrafinch budget is final.\n", title="Q3")
    artifact_id = _artifact_id(first)
    indexed_artifacts.append(artifact_id)
    assert _artifact(db_session, artifact_id).index_status == (
        ChatArtifactIndexStatus.PENDING
    )

    _index(artifact_id)

    chunks = _chunks(db_session, artifact_id)
    assert chunks
    assert {chunk.source_type for chunk in chunks} == {DocumentSource.CHAT_ARTIFACT}
    assert {chunk.semantic_identifier for chunk in chunks} == {"report.md - Q3"}
    assert all(
        artifact_url(artifact_id, 1) in (chunk.source_links or {}).values()
        for chunk in chunks
    )
    assert "zebrafinch" in " ".join(chunk.content for chunk in chunks)
    artifact = _artifact(db_session, artifact_id)
    assert (artifact.index_status, artifact.index_attempts) == (
        ChatArtifactIndexStatus.INDEXED,
        1,
    )
    # The task cached the version's text for the content tools.
    assert get_default_file_store().has_file(
        f"{ARTIFACT_TEXT_FILE_PREFIX}{first.file_id}",
        file_origin=FileOrigin.PLAINTEXT_CACHE,
        file_type="text/plain",
    )

    second = _publish(chat, b"# Plan\n\nThe kingfisher budget replaces it.\n")
    artifact = _artifact(db_session, artifact_id)
    assert (artifact.index_status, artifact.index_attempts) == (
        ChatArtifactIndexStatus.PENDING,
        0,
    )
    _index(artifact_id)

    chunks = _chunks(db_session, artifact_id)
    content = " ".join(chunk.content for chunk in chunks)
    assert "kingfisher" in content and "zebrafinch" not in content
    assert all(
        artifact_url(artifact_id, second.version or 0)
        in (chunk.source_links or {}).values()
        for chunk in chunks
    )
    assert _artifact(db_session, artifact_id).index_status == (
        ChatArtifactIndexStatus.INDEXED
    )


def test_a_file_with_no_text_is_found_by_its_name_and_links_to_its_version(
    db_session: Session, owner: User, indexed_artifacts: list[UUID]
) -> None:
    artifact_id = _artifact_id(
        _publish(_chat(db_session, owner), b"\n", name="blank.md")
    )
    indexed_artifacts.append(artifact_id)

    _index(artifact_id)

    chunks = _chunks(db_session, artifact_id)
    assert chunks
    assert all(
        (chunk.source_links or {}).get(0) == artifact_url(artifact_id, 1)
        for chunk in chunks
    )


@pytest.mark.parametrize("change", ["publish", "pickup"])
def test_a_change_after_the_pickup_skips_the_write_and_leaves_the_artifact_pending(
    db_session: Session,
    owner: User,
    indexed_artifacts: list[UUID],
    change: str,
) -> None:
    artifact_id = _artifact_id(_publish(_chat(db_session, owner), b"First draft\n"))
    indexed_artifacts.append(artifact_id)
    real_extract = file_store_utils.get_or_extract_artifact_text

    def extract_then_change(file_id: str, name: str, size: int) -> ArtifactText | None:
        # A publish, or a newer pickup of a worker that took over after this
        # one ran past its lock, lands before the write.
        db_session.execute(
            update(ChatArtifact)
            .where(ChatArtifact.id == artifact_id)
            .values(
                updated_at=ChatArtifact.updated_at + timedelta(seconds=1)
                if change == "publish"
                else ChatArtifact.updated_at,
                index_attempts=ChatArtifact.index_attempts
                + (1 if change == "pickup" else 0),
            )
        )
        db_session.commit()
        return real_extract(file_id, name, size)

    with patch.object(tasks, "get_or_extract_artifact_text", extract_then_change):
        _index(artifact_id)

    assert not _chunks(db_session, artifact_id)
    artifact = _artifact(db_session, artifact_id)
    assert artifact.index_status == ChatArtifactIndexStatus.PENDING


def test_a_swap_during_the_write_leaves_the_artifact_pending(
    db_session: Session, owner: User, indexed_artifacts: list[UUID]
) -> None:
    artifact_id = _artifact_id(_publish(_chat(db_session, owner), b"First draft\n"))
    indexed_artifacts.append(artifact_id)
    real_extract = file_store_utils.get_or_extract_artifact_text

    def extract_then_swap(file_id: str, name: str, size: int) -> ArtifactText | None:
        # A swap commits after the pickup, while the task writes the old
        # index: its statement resets the artifact.
        db_session.execute(
            update(ChatArtifact)
            .where(ChatArtifact.id == artifact_id)
            .values(index_status=ChatArtifactIndexStatus.PENDING, index_attempts=0)
        )
        db_session.commit()
        return real_extract(file_id, name, size)

    with patch.object(tasks, "get_or_extract_artifact_text", extract_then_swap):
        _index(artifact_id)

    artifact = _artifact(db_session, artifact_id)
    assert (artifact.index_status, artifact.index_attempts) == (
        ChatArtifactIndexStatus.PENDING,
        0,
    )


def test_each_pickup_counts_and_the_last_one_marks_the_artifact_failed(
    db_session: Session, owner: User
) -> None:
    artifact_id = _artifact_id(_publish(_chat(db_session, owner), b"Report\n"))

    for pickup in range(1, CHAT_ARTIFACT_INDEX_MAX_ATTEMPTS + 1):
        # SystemExit is not an Exception: like a worker the kernel kills, it
        # skips every except clause.
        with (
            patch.object(tasks, "get_or_extract_artifact_text", side_effect=SystemExit),
            pytest.raises(SystemExit),
        ):
            _index(artifact_id)
        artifact = _artifact(db_session, artifact_id)
        assert (artifact.index_status, artifact.index_attempts) == (
            ChatArtifactIndexStatus.PENDING,
            pickup,
        )

    with patch.object(tasks, "get_or_extract_artifact_text") as extract:
        _index(artifact_id)

    extract.assert_not_called()
    assert _artifact(db_session, artifact_id).index_status == (
        ChatArtifactIndexStatus.FAILED
    )


def test_a_deleted_chat_removes_the_document_without_marking_it_indexed(
    db_session: Session, owner: User, indexed_artifacts: list[UUID]
) -> None:
    chat = _chat(db_session, owner)
    artifact_id = _artifact_id(_publish(chat, b"Report on the ospreys\n"))
    indexed_artifacts.append(artifact_id)
    _index(artifact_id)
    assert _chunks(db_session, artifact_id)

    # A publish that raced the chat's delete left the artifact PENDING.
    chat.deleted = True
    db_session.execute(
        update(ChatArtifact)
        .where(ChatArtifact.id == artifact_id)
        .values(index_status=ChatArtifactIndexStatus.PENDING)
    )
    db_session.commit()
    _index(artifact_id)

    assert _chunks(db_session, artifact_id) == []
    assert _artifact(db_session, artifact_id).index_status == (
        ChatArtifactIndexStatus.REMOVED
    )


def test_a_failed_bulk_delete_takes_the_later_chats_artifacts_out_of_search(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, owner: User
) -> None:
    """The second chat's cleanup fails after the delete marked every chat
    deleted; the chat that the cleanup did not reach is deleted, so its
    artifact leaves search too."""
    artifact_by_chat = {
        chat.id: _artifact_id(_publish(chat, b"Gulls\n"))
        for chat in (_chat(db_session, owner) for _ in range(3))
    }
    cleaned: list[UUID] = []
    real_cleanup = chat_db.delete_messages_and_files_from_chat_session

    def cleanup(chat_session_id: UUID, session: Session) -> None:
        cleaned.append(chat_session_id)
        if len(cleaned) == 2:
            raise RuntimeError("cleanup failed")
        real_cleanup(chat_session_id, session)

    monkeypatch.setattr(chat_db, "delete_messages_and_files_from_chat_session", cleanup)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        delete_all_chat_sessions_for_user(owner, db_session, hard_delete=True)
    db_session.rollback()

    [unreached] = set(artifact_by_chat) - set(cleaned)
    assert _artifact(db_session, artifact_by_chat[unreached]).index_status == (
        ChatArtifactIndexStatus.REMOVED
    )


def test_an_artifact_with_no_available_version_is_not_marked_indexed(
    db_session: Session, owner: User, indexed_artifacts: list[UUID]
) -> None:
    published = _publish(_chat(db_session, owner), b"Report on the plovers\n")
    artifact_id = _artifact_id(published)
    indexed_artifacts.append(artifact_id)
    _index(artifact_id)
    assert _chunks(db_session, artifact_id)

    # Its stored object is missing, so no version is available.
    db_session.execute(
        update(FileRecord)
        .where(FileRecord.file_id == published.file_id)
        .values(file_size=FILE_SIZE_MISSING_SENTINEL)
    )
    db_session.execute(
        update(ChatArtifact)
        .where(ChatArtifact.id == artifact_id)
        .values(index_status=ChatArtifactIndexStatus.PENDING, index_attempts=0)
    )
    db_session.commit()
    _index(artifact_id)

    assert _chunks(db_session, artifact_id) == []
    artifact = _artifact(db_session, artifact_id)
    assert (artifact.index_status, artifact.index_attempts) == (
        ChatArtifactIndexStatus.PENDING,
        1,
    )


def test_a_missing_artifact_removes_its_document(
    db_session: Session, owner: User, indexed_artifacts: list[UUID]
) -> None:
    published = _publish(_chat(db_session, owner), b"Report on the cranes\n")
    artifact_id = _artifact_id(published)
    indexed_artifacts.append(artifact_id)
    _index(artifact_id)
    assert _chunks(db_session, artifact_id)

    delete_chat_artifact_files([published.file_id])
    db_session.execute(delete(ChatArtifact).where(ChatArtifact.id == artifact_id))
    db_session.commit()
    _index(artifact_id)

    assert _chunks(db_session, artifact_id) == []


def test_a_publish_over_a_stopped_delete_removes_the_old_document(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    owner: User,
    indexed_artifacts: list[UUID],
) -> None:
    """A delete that removed every file but not the artifact row leaves the
    row and its document. A publish at its path replaces the row with a new
    artifact and removes the old document."""
    chat = _chat(db_session, owner)
    artifact_id = _artifact_id(_publish(chat, b"Report on the egrets\n"))
    indexed_artifacts.append(artifact_id)
    _index(artifact_id)
    assert _chunks(db_session, artifact_id)

    real_delete_files = chat_db.delete_chat_artifact_files

    def delete_then_stop(
        file_ids: Sequence[str],
    ) -> None:
        real_delete_files(file_ids)
        raise RuntimeError("The pod stopped")

    monkeypatch.setattr(chat_db, "delete_chat_artifact_files", delete_then_stop)
    with pytest.raises(RuntimeError):
        delete_chat_artifact(artifact_id)
    monkeypatch.undo()

    new_id = _artifact_id(_publish(chat, b"Report on the ibises\n"))
    indexed_artifacts.append(new_id)

    assert new_id != artifact_id
    assert _chunks(db_session, artifact_id) == []


def test_a_failed_publish_of_a_new_version_reindexes_the_older_one(
    db_session: Session, owner: User, indexed_artifacts: list[UUID]
) -> None:
    chat = _chat(db_session, owner)
    artifact_id = _artifact_id(_publish(chat, b"The heron count is final.\n"))
    indexed_artifacts.append(artifact_id)
    _index(artifact_id)
    # The beat indexes the call's new version before the call fails.
    unpublished = _publish(chat, b"The stork count replaces it.\n")
    _index(artifact_id)
    assert "stork" in " ".join(c.content for c in _chunks(db_session, artifact_id))

    assert delete_unpublished_chat_artifacts([unpublished]) == []
    artifact = _artifact(db_session, artifact_id)
    assert (artifact.index_status, artifact.index_attempts) == (
        ChatArtifactIndexStatus.PENDING,
        0,
    )
    _index(artifact_id)

    content = " ".join(chunk.content for chunk in _chunks(db_session, artifact_id))
    assert "heron" in content and "stork" not in content


def test_the_beat_sends_each_pending_artifact_once(
    db_session: Session, owner: User
) -> None:
    chat = _chat(db_session, owner)
    pending = _artifact_id(_publish(chat, b"Pending\n", name="pending.md"))
    done = _artifact_id(_publish(chat, b"Done\n", name="done.md"))
    failed = _artifact_id(_publish(chat, b"Failed\n", name="failed.md"))
    deleted_chat = _chat(db_session, owner)
    in_deleted_chat = _artifact_id(_publish(deleted_chat, b"Gone\n"))
    _delete_chat(db_session, deleted_chat)
    for artifact_id, status in (
        (done, ChatArtifactIndexStatus.INDEXED),
        (failed, ChatArtifactIndexStatus.FAILED),
    ):
        db_session.execute(
            update(ChatArtifact)
            .where(ChatArtifact.id == artifact_id)
            .values(index_status=status)
        )
    db_session.commit()
    cache = get_cache_backend(tenant_id=_TENANT)
    app = MagicMock()
    # The beat reserves an artifact's key only when it is absent, so every
    # sent ID's key belongs to this test, also for other tests' artifacts.
    reserved: set[str] = set()

    def beat() -> list[str]:
        app.send_task.reset_mock()
        with (
            patch.object(
                type(check_for_chat_artifact_indexing.run.__self__),
                "app",
                new_callable=PropertyMock,
                return_value=app,
            ),
            patch.object(tasks, "celery_get_broker_client"),
            patch.object(tasks, "celery_get_queue_length", return_value=0),
            # Every PENDING artifact of the shared database fits one tick.
            patch.object(tasks, "USER_FILE_PROCESSING_MAX_QUEUE_DEPTH", 1_000_000),
        ):
            check_for_chat_artifact_indexing.run(
                tenant_id=_TENANT  # ty: ignore[invalid-argument-type]
            )
        sent_ids = [
            call.kwargs["kwargs"]["artifact_id"] for call in app.send_task.mock_calls
        ]
        reserved.update(sent_ids)
        return sent_ids

    try:
        sent_ids = beat()
        assert str(pending) in sent_ids
        assert str(done) not in sent_ids and str(failed) not in sent_ids
        assert str(in_deleted_chat) not in sent_ids
        [sent] = [
            call
            for call in app.send_task.mock_calls
            if call.kwargs["kwargs"]["artifact_id"] == str(pending)
        ]
        assert sent.args == (OnyxCeleryTask.PROCESS_SINGLE_CHAT_ARTIFACT,)
        assert sent.kwargs == {
            "kwargs": {"artifact_id": str(pending), "tenant_id": _TENANT},
            "queue": OnyxCeleryQueues.USER_FILE_PROCESSING,
            "priority": OnyxCeleryPriority.LOW,
            "expires": CELERY_USER_FILE_PROCESSING_TASK_EXPIRES,
        }
        # Its task is still queued.
        assert str(pending) not in beat()
    finally:
        for artifact_id in reserved:
            cache.delete(chat_artifact_queued_key(UUID(artifact_id)))


def test_the_beat_fills_the_shared_queue_only_to_its_depth() -> None:
    """The user file queue holds 400 tasks of its depth of 500, so the beat
    sends 100 of the 200 PENDING artifacts."""
    pending = sorted(uuid4() for _ in range(200))
    cache = get_cache_backend(tenant_id=_TENANT)
    app = MagicMock()
    try:
        with (
            patch.object(
                type(check_for_chat_artifact_indexing.run.__self__),
                "app",
                new_callable=PropertyMock,
                return_value=app,
            ),
            patch.object(tasks, "celery_get_broker_client"),
            patch.object(tasks, "celery_get_queue_length", return_value=400),
            patch.object(tasks, "USER_FILE_PROCESSING_MAX_QUEUE_DEPTH", 500),
            patch.object(
                tasks,
                "fetch_pending_chat_artifact_ids",
                lambda _db_session, limit: pending[:limit],
            ),
        ):
            check_for_chat_artifact_indexing.run(
                tenant_id=_TENANT  # ty: ignore[invalid-argument-type]
            )
        assert [
            call.kwargs["kwargs"]["artifact_id"] for call in app.send_task.mock_calls
        ] == [str(artifact_id) for artifact_id in pending[:100]]
    finally:
        for artifact_id in pending:
            cache.delete(chat_artifact_queued_key(artifact_id))


def test_a_model_swap_makes_every_artifact_pending_again(
    db_session: Session, owner: User
) -> None:
    chat = _chat(db_session, owner)
    deleted_chat = _chat(db_session, owner)
    artifact_ids = [
        _artifact_id(_publish(chat, b"x\n", name=name))
        for name in ("indexed.md", "failed.md")
    ]
    in_deleted_chat = _artifact_id(_publish(deleted_chat, b"x\n"))
    _delete_chat(db_session, deleted_chat)
    for artifact_id, status in zip(
        artifact_ids,
        (ChatArtifactIndexStatus.INDEXED, ChatArtifactIndexStatus.FAILED),
        strict=True,
    ):
        db_session.execute(
            update(ChatArtifact)
            .where(ChatArtifact.id == artifact_id)
            .values(index_status=status, index_attempts=2)
        )
    db_session.commit()

    try:
        # Not committed: the statement covers every artifact of the shared
        # database.
        flag_chat_artifacts_for_reindex__no_commit(db_session)

        for artifact_id in artifact_ids:
            artifact = db_session.get_one(ChatArtifact, artifact_id)
            db_session.refresh(artifact)
            assert (artifact.index_status, artifact.index_attempts) == (
                ChatArtifactIndexStatus.PENDING,
                0,
            )
        artifact = db_session.get_one(ChatArtifact, in_deleted_chat)
        db_session.refresh(artifact)
        assert artifact.index_status == ChatArtifactIndexStatus.REMOVED
    finally:
        db_session.rollback()


def test_an_email_change_reindexes_the_owners_artifacts_with_the_new_email(
    db_session: Session, owner: User, indexed_artifacts: list[UUID]
) -> None:
    artifact_id = _artifact_id(_publish(_chat(db_session, owner), b"Tern notes\n"))
    indexed_artifacts.append(artifact_id)
    deleted_chat = _chat(db_session, owner)
    in_deleted_chat = _artifact_id(_publish(deleted_chat, b"Gull notes\n"))
    _delete_chat(db_session, deleted_chat)
    _index(artifact_id)
    assert _artifact(db_session, artifact_id).index_status == (
        ChatArtifactIndexStatus.INDEXED
    )
    old_email = owner.email

    new_email = f"renamed-{uuid4().hex[:8]}@example.com"
    reconcile_user_email__no_commit(owner.id, new_email, db_session)
    db_session.commit()

    artifact = _artifact(db_session, artifact_id)
    assert (artifact.index_status, artifact.index_attempts) == (
        ChatArtifactIndexStatus.PENDING,
        0,
    )
    assert _artifact(db_session, in_deleted_chat).index_status == (
        ChatArtifactIndexStatus.REMOVED
    )

    _index(artifact_id)

    assert _chunks(db_session, artifact_id, acl_email=new_email)
    assert _chunks(db_session, artifact_id, acl_email=old_email) == []
    assert _artifact(db_session, artifact_id).index_status == (
        ChatArtifactIndexStatus.INDEXED
    )


def _manage(owner: User, operation: dict[str, JsonValue]) -> None:
    [result] = artifact_operations.manage(
        owner.id,
        CancellationSignal(),
        ManageLibraryArguments.model_validate({"operations": [operation]}),
        conflict_message=str,
    ).results
    assert result.ok, result.error


@pytest.mark.parametrize("operation", ["replace", "rename", "update", "restore"])
def test_a_changed_artifact_is_indexed_again(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    owner: User,
    indexed_artifacts: list[UUID],
    operation: str,
) -> None:
    """A replace, rename, update or restore of an indexed artifact makes it
    PENDING and sends its indexing task after the commit, and the task
    indexes the change."""
    chat = _chat(db_session, owner)
    artifact_id = _artifact_id(_publish(chat, b"The heron count is final.\n"))
    indexed_artifacts.append(artifact_id)
    newest = _publish(chat, b"The stork count replaces it.\n")
    source = _publish(chat, b"The ibis count is final.\n", name="ibis.md")
    _index(artifact_id)
    assert _artifact(db_session, artifact_id).index_status == (
        ChatArtifactIndexStatus.INDEXED
    )
    # The status that a new session reads when each task goes out.
    sent: list[ChatArtifactIndexStatus] = []

    def send_task(name: str, *, kwargs: dict[str, str], **_options: object) -> None:
        assert name == OnyxCeleryTask.PROCESS_SINGLE_CHAT_ARTIFACT
        assert kwargs["artifact_id"] == str(artifact_id)
        with get_session_with_current_tenant() as session:
            sent.append(session.get_one(ChatArtifact, artifact_id).index_status)

    monkeypatch.setattr(client_app, "send_task", send_task)
    try:
        if operation == "replace":
            turn = MagicMock(spec=SandboxTurn)
            turn.user_id = owner.id
            turn.start_call.return_value.session_id = chat.id
            turn.sandbox.read_file.return_value = b"The egret count replaces it.\n"
            artifact_operations.replace_file(
                turn,
                CancellationSignal(),
                LibraryReplaceLibraryFileArguments(
                    library_file_id=artifact_id, file="egrets.md"
                ),
            )
        elif operation == "rename":
            _manage(
                owner,
                {
                    "operation": "rename",
                    "target": {"library_file_id": str(artifact_id)},
                    "new_name": "herons.md",
                },
            )
        elif operation == "update":
            _manage(
                owner,
                {
                    "operation": "update",
                    "library_file_id": str(artifact_id),
                    "file_uri": {"file_id": source.file_id},
                },
            )
        else:
            _manage(
                owner,
                {
                    "operation": "restore_version",
                    "library_file_id": str(artifact_id),
                    "version_number": (newest.version or 0) - 1,
                },
            )
    finally:
        get_cache_backend(tenant_id=_TENANT).delete(
            chat_artifact_queued_key(artifact_id)
        )

    assert sent == [ChatArtifactIndexStatus.PENDING]
    _index(artifact_id)
    chunks = _chunks(db_session, artifact_id)
    content = " ".join(chunk.content for chunk in chunks)
    expected = {
        "replace": "egret",
        "rename": "stork",
        "update": "ibis",
        "restore": "heron",
    }[operation]
    assert expected in content
    assert operation == "rename" or "stork" not in content
    assert {chunk.semantic_identifier for chunk in chunks} == {
        "herons.md" if operation == "rename" else "report.md"
    }
    assert _artifact(db_session, artifact_id).index_status == (
        ChatArtifactIndexStatus.INDEXED
    )


def test_a_deleted_artifact_leaves_the_index(
    db_session: Session, owner: User, indexed_artifacts: list[UUID]
) -> None:
    artifact_id = _artifact_id(_publish(_chat(db_session, owner), b"Crane survey\n"))
    indexed_artifacts.append(artifact_id)
    _index(artifact_id)
    assert _chunks(db_session, artifact_id)

    _manage(
        owner,
        {"operation": "delete", "target": {"library_file_id": str(artifact_id)}},
    )

    assert _chunks(db_session, artifact_id) == []
