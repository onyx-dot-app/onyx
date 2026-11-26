"""The PDF preview of a PowerPoint or Word chat file against
FirecrackerHarnessSandbox with a fake host agent. `POST
/chat/file/{file_id}/preview` converts the file in its owner's sandbox,
whoever asks, and links the PDF to the file's user file or artifact version;
`GET /chat/file/{file_id}?preview=pdf` serves only the linked PDF. The
deletes of the user file, the version and the user remove it. Errors: 404
without access, 422 PREVIEW_UNAVAILABLE when no PDF can be made now, 409
PREVIEW_NOT_READY from the GET before a conversion, 503 when the sandbox
cannot start or be reached now."""

import threading
from collections.abc import Callable, Generator
from io import BytesIO
from uuid import UUID, uuid4

import grpc
import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from onyx.access.access import user_can_access_chat_file
from onyx.background.celery.tasks.user_file_processing import (
    tasks as user_file_tasks,
)
from onyx.cache.interface import CacheBackend
from onyx.chat import file_preview
from onyx.configs.constants import DEFAULT_PERSONA_ID, FileOrigin
from onyx.db import chat as chat_db
from onyx.db import users as users_db
from onyx.db.chat import (
    append_copied_artifact_version,
    create_chat_session,
    delete_chat_artifact_files,
    get_user_published_file,
    link_chat_file_preview,
    save_chat_artifact,
    save_chat_file_preview,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ChatSessionSharedStatus, UserFileStatus
from onyx.db.models import (
    ChatArtifactVersion,
    FileRecord,
    Sandbox,
    User,
    UserFile,
)
from onyx.db.sandbox import get_or_create_sandbox
from onyx.db.users import delete_user_from_db
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_processing.file_types import (
    PDF_MIME_TYPE,
    PRESENTATION_MIME_TYPE,
    WORD_PROCESSING_MIME_TYPE,
)
from onyx.file_store.constants import ARTIFACT_TEXT_FILE_PREFIX
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.file_store.utils import save_chat_output_file
from onyx.microvm.agent_client import HostAgentErrorReason
from onyx.microvm.generated.sandboxd.v1 import sandboxd_pb2
from onyx.server.features.build.sandbox import harness_factory
from onyx.server.features.build.sandbox.firecracker import (
    harness_sandbox,
    harness_state,
)
from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
    FirecrackerHarnessSandbox,
)
from onyx.server.query_and_chat import chat_backend
from onyx.server.query_and_chat.chat_backend import (
    fetch_chat_file,
    make_chat_file_preview,
)
from onyx.tools.tool_implementations.sandbox.models import ArtifactAtPath, KeptTitle
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.microvm.conftest import (
    TENANT_ID,
    AddNode,
    forget_sandbox_keys,
)
from tests.external_dependency_unit.microvm.fake_agent import (
    ANY_PATH,
    InsecureClientFactory,
    RunningFakeAgent,
    WriteFailure,
)
from tests.external_dependency_unit.microvm.test_sandbox_tools import _wait_until

pytestmark = pytest.mark.usefixtures("tenant_context", "initialize_file_store")


@pytest.fixture
def sandbox(
    monkeypatch: pytest.MonkeyPatch, client_factory: InsecureClientFactory
) -> FirecrackerHarnessSandbox:
    """The process's harness sandbox, on the fake agents."""
    instance = FirecrackerHarnessSandbox(
        template="tpl-1", client_factory=client_factory
    )
    monkeypatch.setattr(harness_factory, "HARNESS_SANDBOX_ENABLED", True)
    monkeypatch.setattr(harness_factory, "_instance", instance)
    return instance


@pytest.fixture
def node(add_node: AddNode) -> RunningFakeAgent:
    return add_node(f"cfp-{uuid4().hex[:6]}")


@pytest.fixture
def user(
    db_session: Session, tenant_cache: CacheBackend, make_test_user: MakeTestUser
) -> Generator[User, None, None]:
    user = make_test_user("chat_file_preview")
    yield user
    db_session.rollback()
    for sandbox_id in db_session.scalars(
        select(Sandbox.id).where(Sandbox.user_id == user.id)
    ):
        forget_sandbox_keys(tenant_cache, sandbox_id)
        for prefix in harness_state.SANDBOX_STATE_PREFIXES:
            tenant_cache.delete(prefix + str(sandbox_id))


def _upload(
    db_session: Session, user: User, name: str, mime_type: str, data: bytes
) -> UserFile:
    """A chat upload of `user`: its file record and its user file."""
    file_id = get_default_file_store().save_file(
        content=BytesIO(data),
        display_name=name,
        file_origin=FileOrigin.USER_FILE,
        file_type=mime_type,
    )
    user_file = UserFile(
        id=uuid4(),
        user_id=user.id,
        file_id=file_id,
        name=name,
        file_type=mime_type,
        status=UserFileStatus.COMPLETED,
    )
    db_session.add(user_file)
    db_session.commit()
    return user_file


def _open(
    db_session: Session, user: User, file_id: str, etag: str | None = None
) -> Response:
    """`GET /chat/file/{file_id}?preview=pdf`, with `etag` as If-None-Match."""
    return fetch_chat_file(
        file_id,
        Request(
            {
                "type": "http",
                "headers": [] if etag is None else [(b"if-none-match", etag.encode())],
            }
        ),
        parsed=False,
        preview="pdf",
        user=user,
        db_session=db_session,
    )


def _make(db_session: Session, user: User, file_id: str) -> Response:
    """`POST /chat/file/{file_id}/preview`."""
    return make_chat_file_preview(file_id, user=user, db_session=db_session)


def _body(response: Response) -> bytes:
    """The body that `response` sends, through a test client."""
    app = FastAPI()
    app.add_api_route("/", lambda: response)
    return TestClient(app).get("/").content


def _conversions(node: RunningFakeAgent) -> list[str]:
    """The source of each LibreOffice run, in every sandbox of the node."""
    return [
        execution.argv[-1]
        for executions in node.agent.executions.values()
        for execution in executions.values()
        if execution.argv[0] == "soffice"
    ]


def _preview_error(request: Callable[[], Response]) -> OnyxErrorCode:
    with pytest.raises(OnyxError) as raised:
        request()
    return raised.value.error_code


def _linked_preview(db_session: Session, user_file_id: UUID) -> str | None:
    db_session.expire_all()
    return db_session.scalar(
        select(UserFile.preview_file_id).where(UserFile.id == user_file_id)
    )


def _remaining(db_session: Session, file_ids: list[str]) -> list[str]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(FileRecord.file_id).where(FileRecord.file_id.in_(file_ids))
        )
    )


@pytest.mark.usefixtures("sandbox")
@pytest.mark.parametrize(
    ("name", "mime_type"),
    [
        ("Q3 deck.pptx", PRESENTATION_MIME_TYPE),
        ("memo.docx", WORD_PROCESSING_MIME_TYPE),
        # No suffix: the MIME type gives the type.
        ("Quarterly deck", PRESENTATION_MIME_TYPE),
    ],
)
def test_an_upload_converts_once_and_later_opens_serve_the_linked_pdf(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    node: RunningFakeAgent,
    name: str,
    mime_type: str,
) -> None:
    upload = _upload(db_session, user, name, mime_type, b"office bytes")
    sandbox_id = str(get_or_create_sandbox(db_session, user.id).id)

    first = _make(db_session, user, upload.file_id)

    # The fake LibreOffice writes "%PDF-" and the source.
    assert first.status_code == 200
    assert first.media_type == PDF_MIME_TYPE
    assert _body(first) == b"%PDF-office bytes"
    [converted] = _conversions(node)
    assert converted.endswith("/source" + (".docx" if "memo" in name else ".pptx"))
    # The open converts only: it draws no first page.
    assert [
        execution.argv[0] for execution in node.agent.executions[sandbox_id].values()
    ] == ["soffice"]
    preview_file_id = _linked_preview(db_session, upload.id)
    assert preview_file_id is not None
    record = get_default_file_store().read_file_record(preview_file_id)
    assert (record.file_origin, record.file_type) == (
        FileOrigin.CHAT_FILE_PREVIEW,
        PDF_MIME_TYPE,
    )
    # Only the source's preview request serves the PDF.
    assert not user_can_access_chat_file(preview_file_id, user, db_session)

    # The GET by the user file's id serves the linked PDF.
    again = _open(db_session, user, str(upload.id))

    assert again.status_code == 200
    assert again.media_type == PDF_MIME_TYPE
    assert _body(again) == b"%PDF-office bytes"
    assert len(_conversions(node)) == 1

    # The upload was never indexed.
    monkeypatch.setattr(user_file_tasks, "DISABLE_VECTOR_DB", True)
    user_file_tasks.delete_user_file_impl(
        user_file_id=str(upload.id), tenant_id=TENANT_ID, redis_locking=False
    )
    assert _remaining(db_session, [upload.file_id, preview_file_id]) == []


@pytest.mark.usefixtures("sandbox")
def test_a_published_version_without_a_pdf_converts_and_links_it(
    db_session: Session, user: User, node: RunningFakeAgent
) -> None:
    chat_session = create_chat_session(
        db_session, "preview", user.id, persona_id=DEFAULT_PERSONA_ID
    )
    published = save_chat_artifact(
        b"deck",
        name="q3.pptx",
        mime_type=PRESENTATION_MIME_TYPE,
        title=None,
        thumbnail=None,
        preview_pdf=None,
        target=ArtifactAtPath(chat_session_id=chat_session.id, path="/w/q3.pptx"),
    )

    assert _body(_make(db_session, user, published.file_id)) == b"%PDF-deck"
    assert _body(_make(db_session, user, published.file_id)) == b"%PDF-deck"

    assert len(_conversions(node)) == 1
    db_session.expire_all()
    assert (
        db_session.scalar(
            select(ChatArtifactVersion.preview_file_id).where(
                ChatArtifactVersion.file_id == published.file_id
            )
        )
        is not None
    )


@pytest.mark.usefixtures("sandbox")
def test_a_user_without_access_gets_not_found_and_starts_no_render(
    db_session: Session,
    user: User,
    node: RunningFakeAgent,
    make_test_user: MakeTestUser,
) -> None:
    upload = _upload(db_session, user, "deck.pptx", PRESENTATION_MIME_TYPE, b"deck")
    stranger = make_test_user("chat_file_preview_stranger")

    assert _preview_error(lambda: _make(db_session, stranger, upload.file_id)) == (
        OnyxErrorCode.NOT_FOUND
    )

    assert _conversions(node) == []
    assert node.agent.executions == {}


@pytest.mark.usefixtures("node", "sandbox")
@pytest.mark.parametrize("case", ["no_sandbox", "too_large", "no_owning_row"])
def test_a_file_with_no_possible_pdf_gets_preview_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    node: RunningFakeAgent,
    case: str,
) -> None:
    if case == "no_sandbox":
        monkeypatch.setattr(harness_factory, "HARNESS_SANDBOX_ENABLED", False)
        monkeypatch.setattr(harness_factory, "_instance", None)
    if case == "too_large":
        monkeypatch.setattr(file_preview, "RENDER_PREVIEW_MAX_INPUT_BYTES", 3)
    if case == "no_owning_row":
        # A Python tool output: no user file or artifact version owns it, and
        # the chat's owner reads it by its chat stamp.
        file_id = save_chat_output_file(
            b"deck",
            display_name="deck.pptx",
            file_type=PRESENTATION_MIME_TYPE,
            chat_session_id=create_chat_session(
                db_session, "preview", user.id, persona_id=DEFAULT_PERSONA_ID
            ).id,
        )
    else:
        file_id = _upload(
            db_session, user, "deck.pptx", PRESENTATION_MIME_TYPE, b"deck"
        ).file_id

    assert _preview_error(lambda: _make(db_session, user, file_id)) == (
        OnyxErrorCode.PREVIEW_UNAVAILABLE
    )
    assert _conversions(node) == []


def _preview_records(db_session: Session, name: str) -> list[str]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(FileRecord.file_id).where(
                FileRecord.file_origin == FileOrigin.CHAT_FILE_PREVIEW,
                FileRecord.display_name == f"{name} preview",
            )
        )
    )


@pytest.mark.usefixtures("sandbox")
@pytest.mark.parametrize("case", ["fails", "makes_no_pdf", "past_the_budget"])
def test_a_file_that_does_not_convert_gets_preview_unavailable(
    db_session: Session, user: User, node: RunningFakeAgent, case: str
) -> None:
    """The converter fails, exits 0 with no PDF (LibreOffice does when it
    cannot load the file), or runs past the render budget, which starts once
    the VM runs, so a retry would run past it too: 422, and nothing is saved
    or linked, so a later open tries again."""
    if case == "fails":
        node.agent.soffice_end = (sandboxd_pb2.EXITED, 1)
    elif case == "makes_no_pdf":
        node.agent.soffice_loads = False
    else:
        node.agent.soffice_end = (sandboxd_pb2.DEADLINE_EXCEEDED, -1)
    name = f"{uuid4().hex}.pptx"
    upload = _upload(db_session, user, name, PRESENTATION_MIME_TYPE, b"deck")

    assert _preview_error(lambda: _make(db_session, user, upload.file_id)) == (
        OnyxErrorCode.PREVIEW_UNAVAILABLE
    )

    assert len(_conversions(node)) == 1
    assert _linked_preview(db_session, upload.id) is None
    assert _preview_records(db_session, name) == []


@pytest.mark.usefixtures("sandbox")
@pytest.mark.parametrize(
    ("fault", "error_code"),
    [
        ("daemon", OnyxErrorCode.SERVICE_UNAVAILABLE),
        ("wake", OnyxErrorCode.SANDBOX_CAPACITY_UNAVAILABLE),
    ],
)
def test_a_sandbox_that_cannot_convert_now_gets_a_retryable_error(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    node: RunningFakeAgent,
    fault: str,
    error_code: OnyxErrorCode,
) -> None:
    """The guest daemon fails, or the VM cannot start: 503, and nothing is
    saved or linked."""
    if fault == "daemon":
        node.agent.write_failures[ANY_PATH] = WriteFailure(grpc.StatusCode.UNAVAILABLE)
    else:
        node.agent.refuse_create = HostAgentErrorReason.CAPACITY_MEMORY
        monkeypatch.setattr(harness_sandbox, "WAKE_RETRY_SECONDS", 0.3)
    name = f"{uuid4().hex}.pptx"
    upload = _upload(db_session, user, name, PRESENTATION_MIME_TYPE, b"deck")

    assert _preview_error(lambda: _make(db_session, user, upload.file_id)) == error_code
    assert error_code.status_code == 503

    assert _linked_preview(db_session, upload.id) is None
    assert _preview_records(db_session, name) == []


@pytest.mark.usefixtures("sandbox")
def test_the_open_that_links_second_serves_its_pdf_and_deletes_only_its_copy(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    node: RunningFakeAgent,
) -> None:
    """Two first opens at once: the other open links its PDF while this one
    converts."""
    name = f"{uuid4().hex}.pptx"
    upload = _upload(db_session, user, name, PRESENTATION_MIME_TYPE, b"deck")
    winner = save_chat_file_preview(BytesIO(b"%PDF-winner"), name)
    real_link = chat_db.link_chat_file_preview

    def link_after_the_winner(
        session: Session,
        preview_row: UserFile | ChatArtifactVersion,
        preview_file_id: str,
    ) -> bool:
        assert real_link(session, preview_row, winner)
        return real_link(session, preview_row, preview_file_id)

    monkeypatch.setattr(file_preview, "link_chat_file_preview", link_after_the_winner)

    assert _body(_make(db_session, user, upload.file_id)) == b"%PDF-deck"

    assert _linked_preview(db_session, upload.id) == winner
    assert _preview_records(db_session, name) == [winner]
    monkeypatch.setattr(file_preview, "link_chat_file_preview", real_link)
    assert _body(_make(db_session, user, upload.file_id)) == b"%PDF-winner"
    assert len(_conversions(node)) == 1


@pytest.mark.usefixtures("sandbox", "node")
def test_the_link_updates_only_the_oldest_user_file_of_a_shared_file(
    db_session: Session, user: User
) -> None:
    upload = _upload(db_session, user, "deck.pptx", PRESENTATION_MIME_TYPE, b"deck")
    other = UserFile(
        id=uuid4(),
        user_id=user.id,
        file_id=upload.file_id,
        name="deck.pptx",
        file_type=PRESENTATION_MIME_TYPE,
        status=UserFileStatus.COMPLETED,
    )
    db_session.add(other)
    db_session.commit()
    oldest, newest = sorted([upload.id, other.id])

    # The request names the newest user file.
    assert _body(_make(db_session, user, str(newest))) == b"%PDF-deck"

    assert _linked_preview(db_session, oldest) is not None
    assert _linked_preview(db_session, newest) is None


@pytest.mark.usefixtures("sandbox", "node")
def test_a_link_that_fails_deletes_the_saved_pdf(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, user: User
) -> None:
    name = f"{uuid4().hex}.pptx"
    upload = _upload(db_session, user, name, PRESENTATION_MIME_TYPE, b"deck")

    def fail(*_: object) -> bool:
        raise RuntimeError("the database is gone")

    monkeypatch.setattr(file_preview, "link_chat_file_preview", fail)

    with pytest.raises(RuntimeError, match="the database is gone"):
        _make(db_session, user, upload.file_id)

    assert _preview_records(db_session, name) == []


@pytest.mark.usefixtures("sandbox", "node")
def test_a_render_bug_is_not_a_retryable_error(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    user: User,
    sandbox: FirecrackerHarnessSandbox,
) -> None:
    """Only the sandbox's own faults become 503; a bug stays a 500."""
    upload = _upload(db_session, user, "deck.pptx", PRESENTATION_MIME_TYPE, b"deck")

    def broken(*_: object, **__: object) -> None:
        raise ValueError("a bug")

    monkeypatch.setattr(sandbox, "render_preview", broken)

    with pytest.raises(ValueError, match="a bug"):
        _make(db_session, user, upload.file_id)


@pytest.mark.usefixtures("sandbox")
def test_a_user_file_being_deleted_gets_no_conversion(
    db_session: Session, user: User, node: RunningFakeAgent
) -> None:
    upload = _upload(db_session, user, "deck.pptx", PRESENTATION_MIME_TYPE, b"deck")
    upload.status = UserFileStatus.DELETING
    db_session.commit()

    assert _preview_error(lambda: _make(db_session, user, upload.file_id)) == (
        OnyxErrorCode.PREVIEW_UNAVAILABLE
    )

    assert _conversions(node) == []
    assert _linked_preview(db_session, upload.id) is None


@pytest.mark.usefixtures("sandbox")
def test_a_reader_of_a_public_chat_converts_in_the_owners_sandbox(
    db_session: Session,
    user: User,
    node: RunningFakeAgent,
    make_test_user: MakeTestUser,
) -> None:
    """The owner's sandbox converts the file, whoever asks, so the stored
    PDF has the same trust as the file; the reader gets no sandbox."""
    chat_session = create_chat_session(
        db_session, "preview", user.id, persona_id=DEFAULT_PERSONA_ID
    )
    chat_session.shared_status = ChatSessionSharedStatus.PUBLIC
    db_session.commit()
    published = save_chat_artifact(
        b"deck",
        name="q3.pptx",
        mime_type=PRESENTATION_MIME_TYPE,
        title=None,
        thumbnail=None,
        preview_pdf=None,
        target=ArtifactAtPath(chat_session_id=chat_session.id, path="/w/q3.pptx"),
    )
    reader = make_test_user("chat_file_preview_reader")

    first = _make(db_session, reader, published.file_id)

    assert first.status_code == 200
    assert _body(first) == b"%PDF-deck"
    owner_sandbox = str(get_or_create_sandbox(db_session, user.id).id)
    assert list(node.agent.executions) == [owner_sandbox]
    assert (
        db_session.scalars(select(Sandbox.id).where(Sandbox.user_id == reader.id)).all()
        == []
    )

    assert _body(_open(db_session, user, published.file_id)) == b"%PDF-deck"

    assert len(_conversions(node)) == 1


@pytest.mark.usefixtures("sandbox")
def test_the_get_serves_only_a_stored_pdf(
    db_session: Session,
    user: User,
    node: RunningFakeAgent,
    make_test_user: MakeTestUser,
) -> None:
    """409 PREVIEW_NOT_READY until a conversion stores the PDF, then the PDF
    with an ETag that a later GET gets 304 for. 404 without access and 422
    for a file with no PDF preview. The GET never converts."""
    upload = _upload(db_session, user, "deck.pptx", PRESENTATION_MIME_TYPE, b"deck")
    notes = _upload(db_session, user, "notes.md", "text/markdown", b"notes")
    stranger = make_test_user("chat_file_preview_stranger")

    assert _preview_error(lambda: _open(db_session, user, upload.file_id)) == (
        OnyxErrorCode.PREVIEW_NOT_READY
    )
    assert _preview_error(lambda: _open(db_session, stranger, upload.file_id)) == (
        OnyxErrorCode.NOT_FOUND
    )
    assert _preview_error(lambda: _open(db_session, user, notes.file_id)) == (
        OnyxErrorCode.PREVIEW_UNAVAILABLE
    )
    assert _conversions(node) == []
    assert _linked_preview(db_session, upload.id) is None

    _make(db_session, user, upload.file_id)
    stored = _open(db_session, user, upload.file_id)

    etag = f'"{upload.file_id}-preview-pdf-{chat_backend.RESPONSE_POLICY_VERSION}"'
    assert stored.status_code == 200
    assert stored.headers["etag"] == etag
    assert _body(stored) == b"%PDF-deck"
    assert _open(db_session, user, upload.file_id, etag=etag).status_code == 304
    assert len(_conversions(node)) == 1


def test_a_copied_version_gets_its_own_pdf_which_outlives_the_source(
    db_session: Session, user: User
) -> None:
    chat_session = create_chat_session(
        db_session, "preview", user.id, persona_id=DEFAULT_PERSONA_ID
    )
    first = save_chat_artifact(
        b"deck",
        name="q3.pptx",
        mime_type=PRESENTATION_MIME_TYPE,
        title=None,
        thumbnail=b"thumb",
        preview_pdf=BytesIO(b"%PDF-deck"),
        target=ArtifactAtPath(chat_session_id=chat_session.id, path="/w/q3.pptx"),
    )
    if first.artifact_id is None:
        raise AssertionError("a publish gives an artifact")
    source = get_user_published_file(db_session, user.id, file_id=first.file_id)
    if source is None:
        raise AssertionError("the owner finds the published file")

    copied = append_copied_artifact_version(
        source,
        artifact_id=first.artifact_id,
        name="q3.pptx",
        rename=False,
        title=KeptTitle.NEWEST,
        expected_version=None,
        version_reason="copy",
    )

    db_session.expire_all()
    versions = {
        file_id: (thumbnail_file_id, preview_file_id)
        for file_id, thumbnail_file_id, preview_file_id in db_session.execute(
            select(
                ChatArtifactVersion.file_id,
                ChatArtifactVersion.thumbnail_file_id,
                ChatArtifactVersion.preview_file_id,
            ).where(ChatArtifactVersion.artifact_id == first.artifact_id)
        ).tuples()
    }
    old_thumbnail, old_preview = versions[first.file_id]
    new_preview = versions[copied.file_id][1]
    assert old_thumbnail is not None
    assert old_preview is not None and new_preview is not None
    assert new_preview != old_preview
    store = get_default_file_store()
    assert store.read_file(new_preview).read() == b"%PDF-deck"

    delete_chat_artifact_files([first.file_id])

    assert _remaining(db_session, [old_thumbnail, old_preview, new_preview]) == [
        new_preview
    ]


def test_a_user_delete_removes_the_files_of_their_published_versions(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    owner = make_test_user("chat_file_preview_departed")
    chat_session = create_chat_session(
        db_session, "preview", owner.id, persona_id=DEFAULT_PERSONA_ID
    )
    published = save_chat_artifact(
        b"deck",
        name="q3.pptx",
        mime_type=PRESENTATION_MIME_TYPE,
        title=None,
        thumbnail=b"thumb",
        preview_pdf=BytesIO(b"%PDF-deck"),
        target=ArtifactAtPath(chat_session_id=chat_session.id, path="/w/q3.pptx"),
    )
    preview_file_id = db_session.scalar(
        select(ChatArtifactVersion.preview_file_id).where(
            ChatArtifactVersion.file_id == published.file_id
        )
    )
    assert published.thumbnail_file_id is not None and preview_file_id is not None
    file_ids = [published.file_id, published.thumbnail_file_id, preview_file_id]
    try:
        delete_user_from_db(owner, db_session)

        assert _remaining(db_session, file_ids) == []
    finally:
        for file_id in file_ids:
            get_default_file_store().delete_file(file_id, error_on_missing=False)


def _version(file_id: str) -> ChatArtifactVersion:
    """The version of `file_id`, loaded in a session of its own, so other
    threads can read it."""
    with get_session_with_current_tenant() as session:
        return session.scalars(
            select(ChatArtifactVersion).where(ChatArtifactVersion.file_id == file_id)
        ).one()


def _patch_deletes(
    monkeypatch: pytest.MonkeyPatch, after_delete: Callable[[str], None]
) -> None:
    """Run `after_delete` with the ID of each file that the store deletes,
    after its delete and before it commits."""
    store_type = type(get_default_file_store())
    real_delete = store_type.delete_file

    def delete_file(
        self: FileStore,
        file_id: str,
        error_on_missing: bool = True,
        db_session: Session | None = None,
    ) -> None:
        if file_id.startswith(ARTIFACT_TEXT_FILE_PREFIX):
            after_delete(file_id)
        real_delete(self, file_id, error_on_missing, db_session)
        if not file_id.startswith(ARTIFACT_TEXT_FILE_PREFIX):
            after_delete(file_id)

    monkeypatch.setattr(store_type, "delete_file", delete_file)


def test_a_preview_linked_after_a_version_delete_read_its_links_goes_too(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, user: User
) -> None:
    """An open links the version's preview after the delete read the
    version's links: the delete finds it before it removes the version."""
    chat_session = create_chat_session(
        db_session, "preview", user.id, persona_id=DEFAULT_PERSONA_ID
    )
    published = save_chat_artifact(
        b"deck",
        name="q3.pptx",
        mime_type=PRESENTATION_MIME_TYPE,
        title=None,
        thumbnail=b"thumb",
        preview_pdf=None,
        target=ArtifactAtPath(chat_session_id=chat_session.id, path="/w/q3.pptx"),
    )
    preview_row = _version(published.file_id)
    late = save_chat_file_preview(BytesIO(b"%PDF-late"), "q3.pptx")

    def link_after_the_thumbnail(file_id: str) -> None:
        if file_id == published.thumbnail_file_id:
            with get_session_with_current_tenant() as session:
                assert link_chat_file_preview(session, preview_row, late)

    _patch_deletes(monkeypatch, link_after_the_thumbnail)

    delete_chat_artifact_files([published.file_id])

    assert _remaining(db_session, [published.file_id, late]) == []


@pytest.mark.parametrize("deleted", ["version", "user"])
def test_a_link_while_a_delete_holds_the_version_lock_waits_and_links_nothing(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    make_test_user: MakeTestUser,
    deleted: str,
) -> None:
    """A version delete locks the version from its last read of the
    version's links until its file's delete removes it; a user delete from
    its read of the versions' files until its commit removes them. A link
    meanwhile waits, then finds no version, and its copy is the caller's to
    delete."""
    owner_user = make_test_user("chat_file_preview_lock")
    chat_session = create_chat_session(
        db_session, "preview", owner_user.id, persona_id=DEFAULT_PERSONA_ID
    )
    published = save_chat_artifact(
        b"deck",
        name="q3.pptx",
        mime_type=PRESENTATION_MIME_TYPE,
        title=None,
        thumbnail=None,
        preview_pdf=None,
        target=ArtifactAtPath(chat_session_id=chat_session.id, path="/w/q3.pptx"),
    )
    preview_row = _version(published.file_id)
    copy = save_chat_file_preview(BytesIO(b"%PDF-copy"), "q3.pptx")
    # The link worker's backend PID, its result and its error.
    pids: list[int] = []
    linked: list[bool] = []
    errors: list[BaseException] = []
    links: list[threading.Thread] = []

    def link() -> None:
        try:
            with get_session_with_current_tenant() as session:
                pids.append(session.scalar(text("SELECT pg_backend_pid()")))
                linked.append(link_chat_file_preview(session, preview_row, copy))
        except BaseException as e:
            errors.append(e)

    def link_waits_on_a_lock() -> bool:
        # A session of its own each time: a transaction reads one snapshot
        # of pg_stat_activity.
        with get_session_with_current_tenant() as probe:
            return bool(
                probe.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE pid = :pid AND wait_event_type = 'Lock'"
                    ),
                    {"pid": pids[0]},
                )
            )

    def link_meanwhile() -> None:
        links.append(threading.Thread(target=link))
        links[0].start()
        _wait_until(
            lambda: bool(linked or errors) or (bool(pids) and link_waits_on_a_lock())
        )
        assert not linked, "the link did not wait for the delete"

    try:
        if deleted == "version":
            _patch_deletes(
                monkeypatch,
                lambda file_id: (
                    None
                    if links or not file_id.startswith(ARTIFACT_TEXT_FILE_PREFIX)
                    else link_meanwhile()
                ),
            )
            delete_chat_artifact_files([published.file_id])
        else:
            # The user delete calls it after its read of the versions'
            # files, before the cascade.
            real_fetch = users_db.fetch_ee_implementation_or_noop

            def fetch_while_a_link_waits(*args: str) -> Callable[..., object]:
                link_meanwhile()
                return real_fetch(*args)

            monkeypatch.setattr(
                users_db, "fetch_ee_implementation_or_noop", fetch_while_a_link_waits
            )
            delete_user_from_db(owner_user, db_session)
    finally:
        # A failed delete can leave its transaction, which the link waits
        # on, open.
        db_session.rollback()
        for worker in links:
            worker.join(timeout=10)
        get_default_file_store().delete_file(copy, error_on_missing=False)

    assert not any(worker.is_alive() for worker in links)
    assert errors == []
    assert linked == [False]
    assert _remaining(db_session, [published.file_id]) == []


def test_a_linked_file_that_the_store_keeps_fails_the_delete_and_keeps_the_version(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, user: User
) -> None:
    """A store that leaves a linked file in place: the delete raises once it
    finds the file still linked, and keeps the version and its file."""
    chat_session = create_chat_session(
        db_session, "preview", user.id, persona_id=DEFAULT_PERSONA_ID
    )
    published = save_chat_artifact(
        b"deck",
        name="q3.pptx",
        mime_type=PRESENTATION_MIME_TYPE,
        title=None,
        thumbnail=None,
        preview_pdf=BytesIO(b"%PDF-deck"),
        target=ArtifactAtPath(chat_session_id=chat_session.id, path="/w/q3.pptx"),
    )
    preview_file_id = _version(published.file_id).preview_file_id
    assert preview_file_id is not None
    store_type = type(get_default_file_store())
    real_delete = store_type.delete_file
    preview_deletes: list[str] = []

    def keep_the_preview(
        self: FileStore,
        file_id: str,
        error_on_missing: bool = True,
        db_session: Session | None = None,
    ) -> None:
        if file_id != preview_file_id:
            real_delete(self, file_id, error_on_missing, db_session)
            return
        preview_deletes.append(file_id)
        if len(preview_deletes) > 3:
            raise AssertionError("the delete tried the kept file again and again")

    monkeypatch.setattr(store_type, "delete_file", keep_the_preview)

    with pytest.raises(RuntimeError, match="kept the linked files"):
        delete_chat_artifact_files([published.file_id])
    # The user's clean-up deletes the files with the real store.
    monkeypatch.undo()

    assert preview_deletes == [preview_file_id]
    assert _version(published.file_id).preview_file_id == preview_file_id
    assert sorted(_remaining(db_session, [published.file_id, preview_file_id])) == (
        sorted([published.file_id, preview_file_id])
    )
