"""The artifact tools' queries (`db/chat.py:get_user_published_files` and
`get_user_published_file`) against Postgres and the file store: the newest
available version of each artifact, the order and the cursor, the query
match, and the scope of the user's own root chats that are not deleted."""

from datetime import datetime, timedelta, timezone
from itertools import count
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.configs.constants import DEFAULT_PERSONA_ID, FileOrigin
from onyx.db.chat import (
    get_or_create_root_message,
    get_user_published_file,
    get_user_published_files,
    save_chat_artifact,
)
from onyx.db.enums import ChatSessionSharedStatus
from onyx.db.models import (
    ChatArtifact,
    ChatArtifactVersion,
    ChatSession,
    FileRecord,
    User,
)
from onyx.file_store.file_store import FILE_SIZE_MISSING_SENTINEL
from onyx.file_store.utils import save_chat_output_file
from onyx.server.features.build.sandbox.models import session_workspace
from onyx.tools.tool_implementations.sandbox.models import (
    ARTIFACTS_NAME_MAX_CHARS,
    ARTIFACTS_PATH_MAX_CHARS,
    ArtifactCursor,
    ListedArtifact,
    PublishedFile,
)
from tests.external_dependency_unit.conftest import MakeTestUser

pytestmark = pytest.mark.usefixtures("tenant_context", "initialize_file_store")

# Publish times one second apart, so the order does not rest on the clock
_PUBLISHED_AT = datetime(2026, 11, 20, tzinfo=timezone.utc)
_PUBLISH_ORDER = count()


@pytest.fixture
def owner(make_test_user: MakeTestUser) -> User:
    return make_test_user("artifact_listing_owner")


@pytest.fixture
def other(make_test_user: MakeTestUser) -> User:
    return make_test_user("artifact_listing_other")


def _chat(
    db_session: Session,
    user: User,
    title: str | None = "A chat",
    *,
    deleted: bool = False,
    shared: bool = False,
) -> ChatSession:
    chat = ChatSession(
        id=uuid4(),
        user_id=user.id,
        persona_id=DEFAULT_PERSONA_ID,
        description=title,
        deleted=deleted,
        shared_status=ChatSessionSharedStatus.PUBLIC
        if shared
        else ChatSessionSharedStatus.PRIVATE,
    )
    db_session.add(chat)
    db_session.commit()
    return chat


def _publish(
    db_session: Session,
    chat: ChatSession,
    path: str,
    title: str | None = None,
    *,
    published_at: datetime | None = None,
) -> PublishedFile:
    """A file that publish_files saved for the chat at `path`, as the next
    publish, at a time after every earlier one unless `published_at`."""
    name = path.rsplit("/", 1)[-1]
    file = save_chat_artifact(
        name.encode(),
        name=name,
        mime_type="text/plain",
        chat_session_id=chat.id,
        path=path,
        title=title,
        thumbnail=None,
    )
    at = published_at or _PUBLISHED_AT + timedelta(seconds=next(_PUBLISH_ORDER))
    db_session.execute(
        update(ChatArtifact)
        .where(ChatArtifact.id == file.artifact_id)
        .values(updated_at=at)
    )
    db_session.execute(
        update(ChatArtifactVersion)
        .where(ChatArtifactVersion.file_id == file.file_id)
        .values(created_at=at)
    )
    db_session.commit()
    return file


def _list(
    db_session: Session,
    user: User,
    *,
    query: str | None = None,
    chat: ChatSession | None = None,
    limit: int = 50,
    before: ArtifactCursor | None = None,
) -> tuple[list[ListedArtifact], ArtifactCursor | None]:
    """A page and the cursor of the next one, as artifacts_list pages."""
    rows = get_user_published_files(
        db_session,
        user.id,
        query=query,
        chat_session_id=None if chat is None else chat.id,
        limit=limit,
        before=before,
    )
    assert rows is not None
    return [artifact for artifact, _ in rows[:limit]], (
        rows[limit - 1][1] if len(rows) > limit else None
    )


def _ids(entries: list[ListedArtifact]) -> list[str]:
    return [entry.file_id for entry in entries]


def test_the_list_has_the_newest_available_version_of_each_artifact_newest_first(
    db_session: Session, owner: User
) -> None:
    first = _chat(db_session, owner, "First chat")
    second = _chat(db_session, owner, "Second chat")
    report_path = f"{session_workspace(first.id)}/out/report.csv"
    report_v1 = _publish(db_session, first, report_path, "Report")
    notes = _publish(db_session, second, "/tmp/onyx/notes.md")
    report_v2 = _publish(db_session, first, report_path, "Report, revised")

    entries, after = _list(db_session, owner)
    assert after is None
    assert entries == [
        ListedArtifact(
            file_id=report_v2.file_id,
            name="report.csv",
            title="Report, revised",
            path="out/report.csv",
            version=2,
            chat_id=first.id,
            chat_title="First chat",
            published_at=entries[0].published_at,
            size=len(b"report.csv"),
            mime_type="text/plain",
        ),
        ListedArtifact(
            file_id=notes.file_id,
            name="notes.md",
            title=None,
            path="/tmp/onyx/notes.md",
            version=1,
            chat_id=second.id,
            chat_title="Second chat",
            published_at=entries[1].published_at,
            size=len(b"notes.md"),
            mime_type="text/plain",
        ),
    ]
    assert entries[0].published_at > entries[1].published_at

    # A version whose object is gone gives way to the version before it; the
    # artifact keeps its place.
    db_session.execute(
        update(FileRecord)
        .where(FileRecord.file_id == report_v2.file_id)
        .values(file_size=FILE_SIZE_MISSING_SENTINEL)
    )
    db_session.commit()
    entries, _ = _list(db_session, owner)
    assert [(entry.file_id, entry.version, entry.title) for entry in entries] == [
        (report_v1.file_id, 1, "Report"),
        (notes.file_id, 1, None),
    ]


def test_the_query_matches_the_name_title_or_chat_title_in_any_case(
    db_session: Session, owner: User
) -> None:
    sales = _chat(db_session, owner, "Sales Review")
    plain = _chat(db_session, owner, "Plain")
    report = _publish(db_session, plain, "/w/Q3_Report.csv")
    budget = _publish(db_session, plain, "/w/b.xlsx", "Budget at 100%")
    in_sales = _publish(db_session, sales, "/w/x.txt")
    # Only an older version has this title.
    renamed_path = "/w/renamed.txt"
    _publish(db_session, plain, renamed_path, "Old draft")
    renamed = _publish(db_session, plain, renamed_path, "Final")
    db_session.execute(
        update(ChatSession).where(ChatSession.id == plain.id).values(description=None)
    )
    db_session.commit()

    def found(query: str) -> list[str]:
        return _ids(_list(db_session, owner, query=query)[0])

    assert found("q3_report") == [report.file_id]
    assert found("BUDGET") == [budget.file_id]
    assert found("sales review") == [in_sales.file_id]
    assert found("final") == [renamed.file_id]
    assert found("old draft") == []
    # LIKE wildcards are plain characters.
    assert found("%") == [budget.file_id]
    assert found("_") == [report.file_id]
    assert found("nothing like it") == []


def test_the_cursor_pages_through_every_artifact_once(
    db_session: Session, owner: User
) -> None:
    chat = _chat(db_session, owner)
    newest = _publish(db_session, chat, "/w/newest.txt")
    # Three artifacts with one publish time: the artifact ID orders them.
    tied_at = _PUBLISHED_AT - timedelta(days=1)
    tied = [
        _publish(db_session, chat, f"/w/tied-{index}.txt", published_at=tied_at)
        for index in range(3)
    ]
    oldest = _publish(
        db_session, chat, "/w/oldest.txt", published_at=tied_at - timedelta(days=1)
    )

    pages: list[list[str]] = []
    before: ArtifactCursor | None = None
    while True:
        entries, before = _list(db_session, owner, limit=2, before=before)
        pages.append(_ids(entries))
        if before is None:
            break
    tied_order = [
        file.file_id
        for file in sorted(tied, key=lambda file: str(file.artifact_id), reverse=True)
    ]
    assert pages == [
        [newest.file_id, tied_order[0]],
        tied_order[1:],
        [oldest.file_id],
    ]

    # A last page that is full has no cursor.
    entries, after = _list(db_session, owner, limit=5)
    assert len(entries) == 5
    assert after is None


def test_only_the_users_own_root_chats_that_are_not_deleted_are_listed(
    db_session: Session, owner: User, other: User
) -> None:
    own = _chat(db_session, owner, "Mine")
    deleted = _chat(db_session, owner, "Deleted", deleted=True)
    public_of_other = _chat(db_session, other, "Shared with all", shared=True)
    private_of_other = _chat(db_session, other, "Private")
    root_message = get_or_create_root_message(own.id, db_session)
    child = ChatSession(
        id=uuid4(),
        user_id=owner.id,
        persona_id=DEFAULT_PERSONA_ID,
        description="Child",
        spawned_by_message_id=root_message.id,
    )
    db_session.add(child)
    db_session.commit()

    mine = _publish(db_session, own, "/w/mine.txt")
    in_deleted = _publish(db_session, deleted, "/w/deleted.txt")
    in_public = _publish(db_session, public_of_other, "/w/public.txt")
    in_private = _publish(db_session, private_of_other, "/w/private.txt")
    in_child = _publish(db_session, child, "/w/child.txt")

    assert _ids(_list(db_session, owner)[0]) == [mine.file_id]
    assert _ids(_list(db_session, owner, chat=own)[0]) == [mine.file_id]
    for chat in (deleted, public_of_other, private_of_other, child):
        assert (
            get_user_published_files(
                db_session,
                owner.id,
                query=None,
                chat_session_id=chat.id,
                limit=50,
                before=None,
            )
            is None
        )
    assert (
        get_user_published_files(
            db_session,
            owner.id,
            query=None,
            chat_session_id=uuid4(),
            limit=50,
            before=None,
        )
        is None
    )

    assert get_user_published_file(db_session, owner.id, mine.file_id) is not None
    for file in (in_deleted, in_public, in_private, in_child):
        assert get_user_published_file(db_session, owner.id, file.file_id) is None


def test_the_download_lookup_takes_any_version_and_refuses_other_files(
    db_session: Session, owner: User
) -> None:
    chat = _chat(db_session, owner, "Mine")
    first = _publish(db_session, chat, "/w/report.md", "First")
    _publish(db_session, chat, "/w/report.md", "Second")
    # A thumbnail's file record, as publish_files saves one.
    thumbnail_id = str(uuid4())
    db_session.add(
        FileRecord(
            file_id=thumbnail_id,
            display_name="report.md thumbnail",
            file_origin=FileOrigin.CHAT_ARTIFACT_THUMBNAIL,
            file_type="image/jpeg",
            bucket_name="unused",
            object_key=thumbnail_id,
            file_size=3,
        )
    )
    db_session.flush()
    db_session.execute(
        update(ChatArtifactVersion)
        .where(ChatArtifactVersion.file_id == first.file_id)
        .values(thumbnail_file_id=thumbnail_id)
    )
    db_session.commit()
    image = save_chat_output_file(
        b"png",
        display_name="image.png",
        file_type="image/png",
        chat_session_id=chat.id,
    )

    found = get_user_published_file(db_session, owner.id, first.file_id)
    assert found is not None
    assert (found.version, found.title, found.chat_id) == (1, "First", chat.id)
    for file_id in (thumbnail_id, image, str(uuid4())):
        assert get_user_published_file(db_session, owner.id, file_id) is None

    db_session.execute(
        update(FileRecord)
        .where(FileRecord.file_id == first.file_id)
        .values(file_size=FILE_SIZE_MISSING_SENTINEL)
    )
    db_session.commit()
    assert get_user_published_file(db_session, owner.id, first.file_id) is None


def test_a_published_file_belongs_to_its_chats_owner(
    db_session: Session, owner: User
) -> None:
    chat = _chat(db_session, owner)
    file = _publish(db_session, chat, "/w/a.txt")
    artifact = db_session.get_one(ChatArtifact, file.artifact_id)
    assert artifact.user_id == owner.id


def test_a_version_whose_file_is_not_a_published_file_is_refused(
    db_session: Session, owner: User
) -> None:
    """The download lookup takes only CHAT_ARTIFACT records, also when a
    version row names another file."""
    chat = _chat(db_session, owner)
    published = _publish(db_session, chat, "/w/report.md")
    image = save_chat_output_file(
        b"png", display_name="image.png", file_type="image/png", chat_session_id=chat.id
    )
    db_session.add(
        ChatArtifactVersion(artifact_id=published.artifact_id, version=2, file_id=image)
    )
    db_session.commit()

    assert get_user_published_file(db_session, owner.id, published.file_id)
    assert get_user_published_file(db_session, owner.id, image) is None


def test_an_entry_keeps_a_bounded_name_and_path(
    db_session: Session, owner: User
) -> None:
    chat = _chat(db_session, owner)
    long_name = "n" * (ARTIFACTS_NAME_MAX_CHARS + 50) + ".csv"
    deep = "/".join(["folder"] * 80)
    _publish(db_session, chat, f"{session_workspace(chat.id)}/{deep}/{long_name}")

    [entry], _ = _list(db_session, owner)
    assert entry.name == long_name[:ARTIFACTS_NAME_MAX_CHARS]
    assert len(entry.path) == ARTIFACTS_PATH_MAX_CHARS
    assert entry.path.startswith("…")
    assert entry.path.endswith(long_name[-(ARTIFACTS_PATH_MAX_CHARS - 1) :])


def test_a_later_publish_never_moves_the_latest_publish_back(
    db_session: Session, owner: User
) -> None:
    """A publish that waited on the artifact's row lock can have started
    before the publish it waited for; the time only moves forward."""
    chat = _chat(db_session, owner)
    first = _publish(db_session, chat, "/w/a.md")
    ahead = datetime.now(timezone.utc) + timedelta(hours=1)
    db_session.execute(
        update(ChatArtifact)
        .where(ChatArtifact.id == first.artifact_id)
        .values(updated_at=ahead)
    )
    db_session.commit()

    save_chat_artifact(
        b"again",
        name="a.md",
        mime_type="text/plain",
        chat_session_id=chat.id,
        path="/w/a.md",
        title=None,
        thumbnail=None,
    )
    db_session.expire_all()
    assert db_session.get_one(ChatArtifact, first.artifact_id).updated_at == ahead
