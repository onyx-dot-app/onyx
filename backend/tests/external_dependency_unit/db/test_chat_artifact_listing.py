"""The artifact tools' queries (`db/chat.py:get_user_published_files`,
`get_user_published_file` and the search's name match) against Postgres and
the file store: the newest available version of each artifact, each sort and
its cursor, the filters, the name match, and the scope of the user's own
root chats that are not deleted."""

import contextvars
import threading
import time
from datetime import datetime, timedelta, timezone
from itertools import count, product
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from onyx.agents.models import InputSource, RunStatus
from onyx.cache.factory import get_cache_backend
from onyx.chat.chat_processing_checker import ChatTurnAdmission
from onyx.chat.run_store import _stop_key
from onyx.chat.stop_signal_checker import is_stop_requested
from onyx.configs.constants import DEFAULT_PERSONA_ID, MessageType
from onyx.db import chat as db_chat
from onyx.db.chat import (
    delete_chat_session,
    get_or_create_root_message,
    get_user_artifact_search_candidates,
    get_user_published_file,
    get_user_published_files,
    save_chat_artifact,
    update_chat_session_updated_at_timestamp,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ChatSessionSharedStatus
from onyx.db.models import (
    ChatArtifact,
    ChatArtifactVersion,
    ChatInput,
    ChatMessage,
    ChatSession,
    FileRecord,
    User,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import (
    FILE_SIZE_MISSING_SENTINEL,
    get_default_file_store,
)
from onyx.file_store.utils import save_chat_output_file
from onyx.llm.cancellation import CancellationSignal
from onyx.server.features.build.sandbox.harness_base import chat_file_name
from onyx.server.features.build.sandbox.models import (
    HarnessSandboxRef,
    session_workspace,
)
from onyx.server.query_and_chat.chat_backend import (
    delete_chat_session_by_id,
    get_chat_artifact,
)
from onyx.server.query_and_chat.models import ChatArtifactFile
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.sandbox import artifact_operations
from onyx.tools.tool_implementations.sandbox.artifact_operations import replace_file
from onyx.tools.tool_implementations.sandbox.models import (
    ARTIFACTS_CHAT_TITLE_MAX_CHARS,
    ARTIFACTS_NAME_MAX_CHARS,
    ARTIFACTS_PATH_MAX_CHARS,
    ArtifactAtPath,
    ArtifactById,
    ArtifactCursor,
    ArtifactSort,
    ArtifactVersionConflict,
    ChatDeleted,
    FileUri,
    LibraryListFilters,
    LibraryReplaceLibraryFileArguments,
    ListedArtifact,
    ManageLibraryArguments,
    PublishedFile,
    SortOrder,
    UpdateOperation,
    artifact_url,
)
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
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
    thumbnail: bytes | None = None,
) -> PublishedFile:
    """A file that a publish saved for the chat at `path`, as the next
    publish, at a time after every earlier one unless `published_at`."""
    name = path.rsplit("/", 1)[-1]
    file = save_chat_artifact(
        name.encode(),
        name=name,
        mime_type="text/plain",
        target=ArtifactAtPath(chat_session_id=chat.id, path=path),
        title=title,
        thumbnail=thumbnail,
        preview_pdf=None,
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
    chat: ChatSession | None = None,
    filters: LibraryListFilters | None = None,
    sort: ArtifactSort = "modified_at",
    sort_order: SortOrder = "desc",
    limit: int = 50,
    cursor: ArtifactCursor | None = None,
) -> tuple[list[ListedArtifact], ArtifactCursor | None]:
    """A page and the cursor of the next one, as library_list pages."""
    rows = get_user_published_files(
        db_session,
        user.id,
        chat_session_id=None if chat is None else chat.id,
        filters=filters or LibraryListFilters(),
        sort=sort,
        sort_order=sort_order,
        limit=limit,
        cursor=cursor,
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
    report_artifact = db_session.get_one(ChatArtifact, report_v2.artifact_id)
    notes_artifact = db_session.get_one(ChatArtifact, notes.artifact_id)
    assert entries == [
        ListedArtifact(
            library_file_id=report_artifact.id,
            file_id=report_v2.file_id,
            version_number=2,
            file_name="report.csv",
            title="Report, revised",
            artifact_type="sheet",
            mime_type="text/plain",
            file_size_bytes=len(b"report.csv"),
            created_at=report_artifact.created_at,
            modified_at=report_artifact.updated_at,
            chat_id=first.id,
            chat_title="First chat",
            path="out/report.csv",
            url=artifact_url(report_artifact.id, 2),
        ),
        ListedArtifact(
            library_file_id=notes_artifact.id,
            file_id=notes.file_id,
            version_number=1,
            file_name="notes.md",
            title=None,
            artifact_type="report",
            mime_type="text/plain",
            file_size_bytes=len(b"notes.md"),
            created_at=notes_artifact.created_at,
            modified_at=notes_artifact.updated_at,
            chat_id=second.id,
            chat_title="Second chat",
            path="/tmp/onyx/notes.md",
            url=artifact_url(notes_artifact.id, 1),
        ),
    ]
    assert entries[0].modified_at > entries[1].modified_at

    # A version whose object is gone gives way to the version before it; the
    # artifact keeps its place.
    db_session.execute(
        update(FileRecord)
        .where(FileRecord.file_id == report_v2.file_id)
        .values(file_size=FILE_SIZE_MISSING_SENTINEL)
    )
    db_session.commit()
    entries, _ = _list(db_session, owner)
    assert [
        (entry.file_id, entry.version_number, entry.title) for entry in entries
    ] == [
        (report_v1.file_id, 1, "Report"),
        (notes.file_id, 1, None),
    ]


def test_the_search_matches_words_in_the_name_title_or_chat_title_in_any_case(
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

    by_artifact = {
        file.artifact_id: file.file_id for file in (report, budget, in_sales, renamed)
    }

    def found(query: str) -> list[str]:
        """The files whose name, title or chat title has every word of
        `query`; a second, empty-handed query shows that each query matches
        on its own."""
        candidates = get_user_artifact_search_candidates(
            db_session,
            owner.id,
            chat_session_id=None,
            filters=LibraryListFilters(),
            artifact_ids=None,
            term_sets=[query.split(), ["nothing-matches-this"]],
            limit=50,
        )
        assert candidates is not None
        assert not any(matched[1] for _, matched in candidates)
        return sorted(
            by_artifact[artifact_id]
            for artifact_id, matched in candidates
            if matched[0]
        )

    assert found("q3_report") == [report.file_id]
    assert found("BUDGET") == [budget.file_id]
    assert found("sales review") == [in_sales.file_id]
    # Every word, each in any of the three.
    assert found("review x.txt") == [in_sales.file_id]
    assert found("budget review") == []
    assert found("final") == [renamed.file_id]
    assert found("old draft") == []
    # LIKE wildcards are plain characters.
    assert found("%") == [budget.file_id]
    assert found("_") == [report.file_id]
    assert found("nothing like it") == []
    # No words match no file.
    assert found("") == []


@pytest.mark.parametrize(
    ("sort", "sort_order"),
    list(product(["created_at", "modified_at", "name", "size"], ["asc", "desc"])),
)
def test_each_sort_pages_through_every_artifact_once_in_its_order(
    db_session: Session, owner: User, sort: ArtifactSort, sort_order: SortOrder
) -> None:
    first = _chat(db_session, owner, "First")
    second = _chat(db_session, owner, "Second")
    # Each sort has a tie, which the artifact ID orders: the two b.txt files
    # tie on every key, and two other files on each time.
    at = _PUBLISHED_AT - timedelta(days=10)
    for chat, name, modified_days, created_days in (
        (first, "b.txt", 0, 2),
        (second, "b.txt", 0, 2),
        (first, "dd.csv", 1, 0),
        (first, "a.md", 2, 2),
        (second, "ccc.pdf", 1, 1),
    ):
        file = _publish(
            db_session,
            chat,
            f"/w/{name}",
            published_at=at + timedelta(days=modified_days),
        )
        db_session.execute(
            update(ChatArtifact)
            .where(ChatArtifact.id == file.artifact_id)
            .values(created_at=at - timedelta(days=created_days))
        )
    db_session.commit()

    entries, _ = _list(db_session, owner, sort=sort, sort_order=sort_order)
    key = {
        "created_at": lambda entry: entry.created_at,
        "modified_at": lambda entry: entry.modified_at,
        "name": lambda entry: entry.file_name,
        "size": lambda entry: entry.file_size_bytes,
    }[sort]
    expected = _ids(
        sorted(
            entries,
            key=lambda entry: (key(entry), str(entry.library_file_id)),
            reverse=sort_order == "desc",
        )
    )
    assert len(expected) == 5
    assert _ids(entries) == expected

    # Five files in pages of two: three pages, and the last has no cursor.
    paged: list[str] = []
    cursor: ArtifactCursor | None = None
    for page_number in range(3):
        if page_number:
            assert cursor is not None
            assert (cursor.sort, cursor.sort_order) == (sort, sort_order)
        page, cursor = _list(
            db_session,
            owner,
            sort=sort,
            sort_order=sort_order,
            limit=2,
            cursor=cursor,
        )
        paged.extend(_ids(page))
    assert cursor is None
    assert paged == expected

    # A last page that is full has no cursor.
    entries, after = _list(db_session, owner, sort=sort, sort_order=sort_order, limit=5)
    assert len(entries) == 5
    assert after is None


def test_the_filters_keep_files_by_time_extension_and_category(
    db_session: Session, owner: User
) -> None:
    chat = _chat(db_session, owner)
    sheet = _publish(
        db_session, chat, "/w/Old.XLSX", published_at=_PUBLISHED_AT - timedelta(days=10)
    )
    deck = _publish(
        db_session, chat, "/w/deck.pptx", published_at=_PUBLISHED_AT - timedelta(days=1)
    )
    photo = _publish(db_session, chat, "/w/photo.png")
    bare = _publish(db_session, chat, "/w/notes")
    data = _publish(db_session, chat, "/w/data.json")
    deck_created = _PUBLISHED_AT - timedelta(days=5)
    for file, created_at in (
        (sheet, _PUBLISHED_AT - timedelta(days=20)),
        (deck, deck_created),
    ):
        db_session.execute(
            update(ChatArtifact)
            .where(ChatArtifact.id == file.artifact_id)
            .values(created_at=created_at)
        )
    db_session.commit()

    def found(filters: dict[str, object]) -> set[str]:
        entries, _ = _list(
            db_session, owner, filters=LibraryListFilters.model_validate(filters)
        )
        return set(_ids(entries))

    recent = {photo.file_id, bare.file_id, data.file_id}
    # After is inclusive, before exclusive; a date is midnight UTC.
    assert found({"created_after": deck_created.isoformat()}) == recent | {deck.file_id}
    assert found({"created_before": deck_created.isoformat()}) == {sheet.file_id}
    assert found({"modified_before": "2026-11-19"}) == {sheet.file_id}
    assert found({"modified_after": "2026-11-19T00:00:00"}) == recent | {deck.file_id}
    assert found({"modified_after": "2026-11-11", "modified_before": "2026-11-20"}) == {
        deck.file_id
    }

    assert found({"include_file_types": [".xlsx"]}) == {sheet.file_id}
    assert found({"include_file_types": ["PNG", "pptx"]}) == {
        photo.file_id,
        deck.file_id,
    }
    # A file without an extension is not excluded.
    assert found({"exclude_file_types": ["xlsx", ".Png"]}) == {
        deck.file_id,
        bare.file_id,
        data.file_id,
    }

    by_category = {
        category: _list(
            db_session, owner, filters=LibraryListFilters(category=category)
        )[0]
        for category in ("image", "sheet", "slides", "report", "other")
    }
    assert {
        category: set(_ids(entries)) for category, entries in by_category.items()
    } == {
        "image": {photo.file_id},
        "sheet": {sheet.file_id},
        "slides": {deck.file_id},
        "report": set(),
        "other": {bare.file_id, data.file_id},
    }
    # The filter and the entries' artifact_type agree.
    assert all(
        entry.artifact_type == category
        for category, entries in by_category.items()
        for entry in entries
    )
    assert found({"category": "image", "modified_before": "2026-11-19"}) == set()


def test_only_the_users_own_root_chats_that_are_not_deleted_are_listed(
    db_session: Session, owner: User, other: User
) -> None:
    own = _chat(db_session, owner, "Mine")
    deleted = _chat(db_session, owner, "Deleted")
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
    deleted.deleted = True
    db_session.commit()
    in_public = _publish(db_session, public_of_other, "/w/public.txt")
    in_private = _publish(db_session, private_of_other, "/w/private.txt")
    in_child = _publish(db_session, child, "/w/child.txt")

    assert _ids(_list(db_session, owner)[0]) == [mine.file_id]
    assert _ids(_list(db_session, owner, chat=own)[0]) == [mine.file_id]
    for chat_id in (
        deleted.id,
        public_of_other.id,
        private_of_other.id,
        child.id,
        uuid4(),
    ):
        assert (
            get_user_published_files(
                db_session,
                owner.id,
                chat_session_id=chat_id,
                filters=LibraryListFilters(),
                sort="modified_at",
                sort_order="desc",
                limit=50,
                cursor=None,
            )
            is None
        )

    assert (
        get_user_published_file(db_session, owner.id, file_id=mine.file_id) is not None
    )
    for file in (in_deleted, in_public, in_private, in_child):
        assert (
            get_user_published_file(db_session, owner.id, file_id=file.file_id) is None
        )


def test_the_copy_lookup_takes_any_version_and_refuses_other_files(
    db_session: Session, owner: User
) -> None:
    chat = _chat(db_session, owner, "Mine")
    first = _publish(db_session, chat, "/w/report.md", "First", thumbnail=b"jpg")
    thumbnail_id = first.thumbnail_file_id
    assert thumbnail_id is not None
    _publish(db_session, chat, "/w/report.md", "Second")
    image = save_chat_output_file(
        b"png",
        display_name="image.png",
        file_type="image/png",
        chat_session_id=chat.id,
    )
    # Not a published file, so the user teardown leaves it.
    try:
        found = get_user_published_file(db_session, owner.id, file_id=first.file_id)
        assert found is not None
        assert (found.version_number, found.title, found.chat_id) == (
            1,
            "First",
            chat.id,
        )
        for file_id in (thumbnail_id, image, str(uuid4())):
            assert (
                get_user_published_file(db_session, owner.id, file_id=file_id) is None
            )

        db_session.execute(
            update(FileRecord)
            .where(FileRecord.file_id == first.file_id)
            .values(file_size=FILE_SIZE_MISSING_SENTINEL)
        )
        db_session.commit()
        assert (
            get_user_published_file(db_session, owner.id, file_id=first.file_id) is None
        )
    finally:
        db_session.rollback()
        get_default_file_store().delete_file(image, error_on_missing=False)


def test_the_copy_lookup_by_artifact_takes_its_newest_available_version(
    db_session: Session, owner: User, other: User
) -> None:
    chat = _chat(db_session, owner, "Mine")
    first = _publish(db_session, chat, "/w/report.md", "First")
    second = _publish(db_session, chat, "/w/report.md", "Second")
    assert first.artifact_id is not None

    def newest() -> str | None:
        found = get_user_published_file(
            db_session, owner.id, artifact_id=first.artifact_id
        )
        return None if found is None else found.file_id

    assert newest() == second.file_id
    db_session.execute(
        update(FileRecord)
        .where(FileRecord.file_id == second.file_id)
        .values(file_size=FILE_SIZE_MISSING_SENTINEL)
    )
    db_session.commit()
    assert newest() == first.file_id

    assert get_user_published_file(db_session, owner.id, artifact_id=uuid4()) is None
    theirs = _publish(db_session, _chat(db_session, other), "/w/theirs.md")
    assert (
        get_user_published_file(db_session, owner.id, artifact_id=theirs.artifact_id)
        is None
    )
    db_session.execute(
        update(ChatSession).where(ChatSession.id == chat.id).values(deleted=True)
    )
    db_session.commit()
    assert newest() is None


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
    """The copy lookup takes only CHAT_ARTIFACT records, also when a version
    row names another file."""
    chat = _chat(db_session, owner)
    published = _publish(db_session, chat, "/w/report.md")
    image = save_chat_output_file(
        b"png", display_name="image.png", file_type="image/png", chat_session_id=chat.id
    )
    db_session.add(
        ChatArtifactVersion(artifact_id=published.artifact_id, version=2, file_id=image)
    )
    db_session.commit()

    assert get_user_published_file(db_session, owner.id, file_id=published.file_id)
    assert get_user_published_file(db_session, owner.id, file_id=image) is None


def test_a_list_entry_is_bounded_and_the_copy_lookup_is_whole(
    db_session: Session, owner: User
) -> None:
    long_title = "t" * (ARTIFACTS_CHAT_TITLE_MAX_CHARS + 50)
    chat = _chat(db_session, owner, long_title)
    long_name = "n" * (ARTIFACTS_NAME_MAX_CHARS + 10) + ".pptx"
    deep = "/".join(["folder"] * 80)
    published = _publish(
        db_session, chat, f"{session_workspace(chat.id)}/{deep}/{long_name}"
    )

    [entry], _ = _list(db_session, owner)
    assert entry.file_name == long_name[:ARTIFACTS_NAME_MAX_CHARS]
    assert len(entry.path) == ARTIFACTS_PATH_MAX_CHARS
    assert entry.path.startswith("…")
    assert entry.path.endswith(long_name[-(ARTIFACTS_PATH_MAX_CHARS - 1) :])
    assert entry.chat_title == long_title[:ARTIFACTS_CHAT_TITLE_MAX_CHARS]

    # library_prepare_materialize names the copy from the whole name, so it keeps
    # its extension.
    found = get_user_published_file(db_session, owner.id, file_id=published.file_id)
    assert found is not None
    assert (found.file_name, found.chat_title) == (long_name, long_title)
    assert found.path == f"{deep}/{long_name}"
    assert found.artifact_type == "slides"
    assert chat_file_name(found.file_id, found.file_name).endswith(".pptx")


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
        target=ArtifactAtPath(chat_session_id=chat.id, path="/w/a.md"),
        title=None,
        thumbnail=None,
        preview_pdf=None,
    )
    db_session.expire_all()
    assert db_session.get_one(ChatArtifact, first.artifact_id).updated_at == ahead


def test_the_artifact_route_says_how_each_user_may_open_a_version(
    db_session: Session, owner: User, other: User
) -> None:
    chat = _chat(db_session, owner, "Mine")
    first = _publish(db_session, chat, "/w/report.md", "First")
    second = _publish(db_session, chat, "/w/report.md", "Second")
    artifact_id = first.artifact_id
    assert artifact_id is not None

    def opened(user: User, version: int | None = None) -> ChatArtifactFile | None:
        try:
            return get_chat_artifact(
                artifact_id, version, user=user, db_session=db_session
            )
        except OnyxError as error:
            assert error.error_code is OnyxErrorCode.NOT_FOUND
            return None

    newest = opened(owner)
    assert newest is not None
    assert (
        newest.file_id,
        newest.version,
        newest.title,
        newest.chat_id,
        newest.access,
    ) == (second.file_id, 2, "Second", chat.id, "owner")
    assert newest.display_path == "/w/report.md"
    older = opened(owner, 1)
    assert older is not None and older.file_id == first.file_id
    assert opened(owner, 3) is None

    # A chat of another user that holds the first version, as a replace from
    # it would: its owner may open that version alone, by its number.
    holder = _chat(db_session, other, "Theirs")
    root = get_or_create_root_message(holder.id, db_session)
    db_session.add(
        ChatMessage(
            chat_session_id=holder.id,
            parent_message_id=root.id,
            message="Here.",
            token_count=1,
            message_type=MessageType.ASSISTANT,
            files=[{"id": first.file_id, "type": "document", "name": "report.md"}],
        )
    )
    db_session.commit()
    assert opened(other) is None
    assert opened(other, 2) is None
    only_file = opened(other, 1)
    assert only_file is not None
    assert (only_file.file_id, only_file.access) == (first.file_id, "file_only")

    # Every user reads it once the chat is shared.
    db_session.execute(
        update(ChatSession)
        .where(ChatSession.id == chat.id)
        .values(shared_status=ChatSessionSharedStatus.PUBLIC)
    )
    db_session.commit()
    shared = opened(other)
    assert shared is not None
    assert (shared.file_id, shared.access) == (second.file_id, "chat_reader")
    # A version whose object is gone gives way to the version before it.
    db_session.execute(
        update(FileRecord)
        .where(FileRecord.file_id == second.file_id)
        .values(file_size=FILE_SIZE_MISSING_SENTINEL)
    )
    db_session.commit()
    fallback = opened(owner)
    assert fallback is not None and fallback.file_id == first.file_id
    assert opened(owner, 2) is None

    # A deleted chat's files open for no one.
    db_session.execute(
        update(ChatSession).where(ChatSession.id == chat.id).values(deleted=True)
    )
    db_session.commit()
    assert opened(owner) is None
    assert opened(other, 1) is None


def test_concurrent_replaces_take_turns_and_a_stale_one_keeps_nothing(
    db_session: Session, owner: User
) -> None:
    """Replaces of one artifact wait on its row lock: each gets the next
    version, and of two that expect the same version, one fails without a
    file record."""
    chat = _chat(db_session, owner)
    first = _publish(db_session, chat, "/w/a.md")
    artifact_id = first.artifact_id
    assert artifact_id is not None

    def replace_twice(expected: int | None) -> list[int | str]:
        barrier = threading.Barrier(2)
        outcomes: list[int | str] = []

        def replace() -> None:
            barrier.wait()
            try:
                saved = save_chat_artifact(
                    b"next",
                    name="ignored.md",
                    mime_type="text/plain",
                    title=None,
                    thumbnail=None,
                    preview_pdf=None,
                    target=ArtifactById(artifact_id=artifact_id),
                    expected_version=expected,
                )
                outcomes.append(saved.version or 0)
            except ArtifactVersionConflict as error:
                outcomes.append(f"conflict at {error.current_version}")

        threads = [
            threading.Thread(target=contextvars.copy_context().run, args=(replace,))
            for _ in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        return sorted(outcomes, key=str)

    assert replace_twice(None) == [2, 3]
    records = db_session.scalars(select(func.count(FileRecord.file_id))).one()
    assert replace_twice(3) == [4, "conflict at 4"]
    db_session.expire_all()
    assert db_session.scalars(select(func.count(FileRecord.file_id))).one() == (
        records + 1
    )
    versions = db_session.scalars(
        select(ChatArtifactVersion.version).where(
            ChatArtifactVersion.artifact_id == artifact_id
        )
    ).all()
    assert sorted(versions) == [1, 2, 3, 4]


def test_the_expected_version_is_the_newest_available_one(
    db_session: Session, owner: User
) -> None:
    """The check reads the version that the model sees: a newest version
    whose object is gone does not count. The new version still follows the
    highest number."""
    chat = _chat(db_session, owner)
    _publish(db_session, chat, "/w/a.md")
    gone = _publish(db_session, chat, "/w/a.md")
    artifact_id = gone.artifact_id
    assert artifact_id is not None
    db_session.execute(
        update(FileRecord)
        .where(FileRecord.file_id == gone.file_id)
        .values(file_size=FILE_SIZE_MISSING_SENTINEL)
    )
    db_session.commit()

    def save(expected: int) -> PublishedFile:
        return save_chat_artifact(
            b"next",
            name="a.md",
            mime_type="text/plain",
            title=None,
            thumbnail=None,
            preview_pdf=None,
            target=ArtifactById(artifact_id=artifact_id),
            expected_version=expected,
        )

    with pytest.raises(ArtifactVersionConflict) as conflict:
        save(2)
    assert conflict.value.current_version == 1
    assert save(1).version == 3


def test_a_replace_without_a_title_keeps_a_title_published_during_it(
    db_session: Session, owner: User
) -> None:
    """A replace with no title takes the newest version's title when it
    saves, so a new title that another chat publishes while the replace
    reads its file stays. The version names the artifact's chat, not the
    replacing one."""
    owning_chat = _chat(db_session, owner)
    first = _publish(db_session, owning_chat, "/w/a.md", "Old")
    artifact_id = first.artifact_id
    assert artifact_id is not None

    def read_during_a_retitle(*_args: object, **_kwargs: object) -> bytes:
        save_chat_artifact(
            b"retitled",
            name="a.md",
            mime_type="text/plain",
            title="New",
            thumbnail=None,
            preview_pdf=None,
            target=ArtifactById(artifact_id=artifact_id),
        )
        return b"replaced"

    turn = MagicMock(spec=SandboxTurn)
    turn.user_id = owner.id
    turn.start_call.return_value = HarnessSandboxRef(
        tenant_id="tenant",
        sandbox_id=uuid4(),
        session_id=_chat(db_session, owner).id,
    )
    turn.sandbox.read_file.side_effect = read_during_a_retitle

    replaced = replace_file(
        turn,
        CancellationSignal(),
        LibraryReplaceLibraryFileArguments(library_file_id=artifact_id, file="a.md"),
    )

    assert (replaced.version, replaced.title, replaced.chat_id) == (
        3,
        "New",
        owning_chat.id,
    )
    assert (
        db_session.scalar(
            select(ChatArtifactVersion.title).where(
                ChatArtifactVersion.file_id == replaced.file_id
            )
        )
        == "New"
    )


def test_a_replace_into_a_chat_deleted_during_it_writes_no_version(
    db_session: Session, owner: User
) -> None:
    """The artifact's chat is checked under the row lock: a chat deleted
    while the replace reads its file gets the not-found error and no
    version."""
    owning_chat = _chat(db_session, owner)
    first = _publish(db_session, owning_chat, "/w/a.md")
    artifact_id = first.artifact_id
    assert artifact_id is not None

    def read_during_a_delete(*_args: object, **_kwargs: object) -> bytes:
        db_session.execute(
            update(ChatSession)
            .where(ChatSession.id == owning_chat.id)
            .values(deleted=True)
        )
        db_session.commit()
        return b"replaced"

    turn = MagicMock(spec=SandboxTurn)
    turn.user_id = owner.id
    turn.start_call.return_value = HarnessSandboxRef(
        tenant_id="tenant",
        sandbox_id=uuid4(),
        session_id=_chat(db_session, owner).id,
    )
    turn.sandbox.read_file.side_effect = read_during_a_delete

    with pytest.raises(ToolCallException, match="No published file"):
        replace_file(
            turn,
            CancellationSignal(),
            LibraryReplaceLibraryFileArguments(
                library_file_id=artifact_id, file="a.md"
            ),
        )

    assert db_session.scalars(
        select(ChatArtifactVersion.version).where(
            ChatArtifactVersion.artifact_id == artifact_id
        )
    ).all() == [1]


def test_an_update_keeps_a_title_published_after_its_lookup(
    db_session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An update takes the newest version's title when it saves, so a new
    title that another chat publishes after the update looked the file up
    stays."""
    first = _publish(db_session, _chat(db_session, owner), "/w/a.md", "Old")
    source = _publish(db_session, _chat(db_session, owner), "/w/b.md", "Source")
    artifact_id = first.artifact_id
    assert artifact_id is not None
    check = artifact_operations.check_same_type

    def check_after_a_retitle(artifact: ListedArtifact, file: str) -> None:
        save_chat_artifact(
            b"retitled",
            name="a.md",
            mime_type="text/plain",
            title="New",
            thumbnail=None,
            preview_pdf=None,
            target=ArtifactById(artifact_id=artifact_id),
        )
        check(artifact, file)

    monkeypatch.setattr(artifact_operations, "check_same_type", check_after_a_retitle)
    [result] = artifact_operations.manage(
        owner.id,
        CancellationSignal(),
        ManageLibraryArguments(
            operations=[
                UpdateOperation(
                    operation="update",
                    library_file_id=artifact_id,
                    file_uri=FileUri(file_id=source.file_id),
                )
            ]
        ),
        conflict_message=str,
    ).results

    assert (result.ok, result.version_number) == (True, 3)
    assert (
        db_session.scalar(
            select(ChatArtifactVersion.title).where(
                ChatArtifactVersion.file_id == result.file_id
            )
        )
        == "New"
    )


def test_a_publish_into_a_chat_that_a_delete_holds_waits_and_saves_nothing(
    db_session: Session, owner: User
) -> None:
    """A publish to a new path waits for the lock of a chat delete in progress,
    then finds the chat deleted and saves no artifact."""
    chat = _chat(db_session, owner)
    outcome: list[BaseException | PublishedFile] = []

    def publish() -> None:
        try:
            outcome.append(
                save_chat_artifact(
                    b"late",
                    name="late.md",
                    mime_type="text/plain",
                    target=ArtifactAtPath(chat_session_id=chat.id, path="/w/late.md"),
                    title=None,
                    thumbnail=None,
                    preview_pdf=None,
                )
            )
        except BaseException as error:
            outcome.append(error)

    with get_session_with_current_tenant() as deleting:
        deleting.execute(
            update(ChatSession).where(ChatSession.id == chat.id).values(deleted=True)
        )
        publisher = threading.Thread(
            target=contextvars.copy_context().run, args=(publish,)
        )
        publisher.start()
        deadline = time.monotonic() + 10
        while publisher.is_alive() and not deleting.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE pg_backend_pid() = ANY(pg_blocking_pids(pid))"
            )
        ):
            assert time.monotonic() < deadline, "the publish did not wait"
            publisher.join(timeout=0.05)
        deleting.commit()
        publisher.join(timeout=10)

    [result] = outcome
    assert isinstance(result, ChatDeleted)
    assert (
        db_session.scalars(
            select(ChatArtifact.id).where(ChatArtifact.chat_session_id == chat.id)
        ).all()
        == []
    )


def test_a_hard_delete_does_not_deadlock_with_a_send_that_adds_a_message(
    db_session: Session, owner: User
) -> None:
    """A send holds a message of the chat (a response reservation updates the
    parent of its response) and then updates the chat's row. The hard delete
    of the chat waits for the send, and the send does not wait for the
    delete."""
    chat = _chat(db_session, owner)
    root_id = get_or_create_root_message(chat.id, db_session).id
    db_session.commit()
    outcome: list[BaseException | None] = []

    def hard_delete() -> None:
        try:
            with get_session_with_current_tenant() as deleting:
                delete_chat_session(owner.id, chat.id, deleting, hard_delete=True)
            outcome.append(None)
        except BaseException as error:
            outcome.append(error)

    with get_session_with_current_tenant() as sending:
        sending.execute(
            update(ChatMessage)
            .where(ChatMessage.id == root_id)
            .values(latest_child_message_id=None)
        )
        deleter = threading.Thread(
            target=contextvars.copy_context().run, args=(hard_delete,)
        )
        deleter.start()
        deadline = time.monotonic() + 10
        while deleter.is_alive() and not sending.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE pg_backend_pid() = ANY(pg_blocking_pids(pid))"
            )
        ):
            assert time.monotonic() < deadline, "the delete did not wait"
            deleter.join(timeout=0.05)
        sending.execute(text("SET LOCAL lock_timeout = '5s'"))
        update_chat_session_updated_at_timestamp(chat.id, sending)
        sending.commit()
        deleter.join(timeout=10)

    assert outcome == [None]
    assert (
        db_session.scalar(select(ChatSession.id).where(ChatSession.id == chat.id))
        is None
    )


def test_a_hard_delete_of_all_chats_cleans_up_the_chats_a_failed_one_left(
    db_session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    chats = [_chat(db_session, owner), _chat(db_session, owner)]
    delete_messages = db_chat.delete_messages_and_files_from_chat_session
    cleaned: list[UUID] = []

    def clean_up_one_chat(chat_session_id: UUID, session: Session) -> None:
        if cleaned:
            raise RuntimeError("file store down")
        delete_messages(chat_session_id, session)
        cleaned.append(chat_session_id)

    monkeypatch.setattr(
        db_chat, "delete_messages_and_files_from_chat_session", clean_up_one_chat
    )
    stopped: list[UUID] = []
    with pytest.raises(RuntimeError):
        db_chat.delete_all_chat_sessions_for_user(
            owner,
            db_session,
            hard_delete=True,
            on_marked=lambda ids, _artifacts, _running: stopped.extend(ids),
        )
    db_session.rollback()
    monkeypatch.undo()
    assert {chat.id for chat in chats} <= set(stopped)

    deleted_ids, _ = db_chat.delete_all_chat_sessions_for_user(
        owner, db_session, hard_delete=True
    )
    assert {chat.id for chat in chats} <= set(deleted_ids)


def test_a_hard_delete_of_a_chat_that_a_failed_one_left_removes_it(
    db_session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat = _chat(db_session, owner)
    with monkeypatch.context() as failing:
        failing.setattr(
            db_chat,
            "delete_messages_and_files_from_chat_session",
            MagicMock(side_effect=RuntimeError("file store down")),
        )
        with pytest.raises(RuntimeError):
            delete_chat_session_by_id(
                chat.id, hard_delete=True, user=owner, db_session=db_session
            )
    db_session.rollback()
    assert db_session.scalar(
        select(ChatSession.deleted).where(ChatSession.id == chat.id)
    )

    delete_chat_session_by_id(
        chat.id, hard_delete=True, user=owner, db_session=db_session
    )
    assert (
        db_session.scalar(select(ChatSession.id).where(ChatSession.id == chat.id))
        is None
    )


def test_a_chat_delete_stops_the_running_turn(db_session: Session, owner: User) -> None:
    chat = _chat(db_session, owner)
    cache = get_cache_backend()
    turn = ChatTurnAdmission(cache)
    turn.claim(chat.id)
    try:
        turn.publish(41, [])
        delete_chat_session_by_id(
            chat.id, hard_delete=False, user=owner, db_session=db_session
        )
        assert is_stop_requested(chat.id, cache, stream_id=41)
    finally:
        turn.release()
        cache.delete(f"chatsessionstop_fence_{chat.id}_41")


def test_a_chat_delete_stops_its_running_background_agents(
    db_session: Session, owner: User
) -> None:
    chat = _chat(db_session, owner)
    spawn = ChatMessage(
        chat_session_id=chat.id,
        message="Started an agent",
        token_count=1,
        message_type=MessageType.ASSISTANT,
    )
    db_session.add(spawn)
    db_session.flush()
    agent = ChatSession(id=uuid4(), spawned_by_message_id=spawn.id)
    db_session.add(agent)
    db_session.flush()
    running, done = (
        ChatMessage(
            chat_session_id=agent.id,
            message="",
            token_count=0,
            message_type=MessageType.ASSISTANT,
            response_status=status,
        )
        for status in (RunStatus.RUNNING, RunStatus.COMPLETE)
    )
    db_session.add_all([running, done])
    db_session.flush()
    # Queued work would start a run after the delete
    queued = ChatInput(
        recipient_session_id=agent.id,
        message_id="queued",
        source=InputSource.AGENT_RESULT,
        source_response_id=done.id,
        root_response_id=spawn.id,
        content="A result",
    )
    db_session.add(queued)
    db_session.commit()
    queued_id = queued.id
    cache = get_cache_backend()
    try:
        delete_chat_session_by_id(
            chat.id, hard_delete=False, user=owner, db_session=db_session
        )
        assert cache.get(_stop_key(running.id)) == b"user"
        assert cache.get(_stop_key(done.id)) is None
        assert (
            db_session.scalar(select(ChatInput.id).where(ChatInput.id == queued_id))
            is None
        )
    finally:
        cache.delete(_stop_key(running.id))
