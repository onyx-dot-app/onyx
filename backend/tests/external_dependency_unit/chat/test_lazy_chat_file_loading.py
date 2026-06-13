"""External-dependency tests for the lazy chat-file loading path.

These tests guard the OOM fix: ``load_all_chat_files`` and friends must NOT
read raw file bytes from the file store at construction time. Bytes are read
only when a downstream consumer (e.g. PythonTool) actually accesses
``.content``.

Uses real Postgres + real file store; the file_store's ``read_file`` method is
patched at module level with a counting wrapper so we can assert exactly when
S3 reads happen.
"""

from collections.abc import Generator
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.chat.chat_utils import load_all_chat_files
from onyx.chat.chat_utils import load_chat_file
from onyx.chat.models import ChatLoadedFile
from onyx.configs.constants import FileOrigin
from onyx.configs.constants import MessageType
from onyx.db.chat import create_chat_session
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_or_create_root_message
from onyx.file_store import file_store as file_store_module
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import ChatFileType
from onyx.file_store.models import FileDescriptor
from onyx.tools.models import ChatFile
from tests.external_dependency_unit.conftest import create_test_user

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_file(content: bytes, *, file_type: str = "text/plain") -> str:
    return get_default_file_store().save_file(
        content=BytesIO(content),
        display_name=None,
        file_origin=FileOrigin.CHAT_UPLOAD,
        file_type=file_type,
        file_metadata={"test": True},
    )


def _descriptor(
    file_id: str, *, type_: ChatFileType = ChatFileType.PLAIN_TEXT
) -> FileDescriptor:
    return {"id": file_id, "type": type_, "name": f"f_{file_id[:8]}.txt"}


class _ReadCounter:
    """Counts only RAW chat-file byte reads.

    Reads of plaintext-cache files (``__plaintext__`` prefix) are intentionally
    excluded — we want to measure original-file fetches that would dominate
    memory, not the small cached plaintext store that's already a fast path.
    """

    def __init__(self) -> None:
        self.count = 0
        self.read_ids: list[str] = []

    def hits_for(self, file_id: str) -> int:
        return self.read_ids.count(file_id)


@pytest.fixture
def read_counter(
    db_session: Session,  # noqa: ARG001 — keeps tenant + file_store fixtures live
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
) -> Generator[_ReadCounter, None, None]:
    """Patch ``S3BackedFileStore.read_file`` to count raw chat-file reads."""
    counter = _ReadCounter()
    real_read_file = file_store_module.S3BackedFileStore.read_file

    def _counting_read_file(self, file_id, mode=None, use_tempfile=False):  # type: ignore[no-untyped-def]
        # Plaintext-cache reads use the ``plaintext_{file_id}`` naming
        # convention (see onyx.file_store.utils.plaintext_file_name_for_id).
        # These are by-design cheap and are not the OOM-relevant load — skip
        # counting them.
        if isinstance(file_id, str) and file_id.startswith("plaintext_"):
            return real_read_file(self, file_id, mode=mode, use_tempfile=use_tempfile)
        counter.count += 1
        counter.read_ids.append(file_id)
        return real_read_file(self, file_id, mode=mode, use_tempfile=use_tempfile)

    with patch.object(
        file_store_module.S3BackedFileStore, "read_file", _counting_read_file
    ):
        yield counter


@pytest.fixture
def file_cleanup(
    db_session: Session,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
) -> Generator[list[str], None, None]:
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
# Lazy InMemoryChatFile / ChatLoadedFile / ChatFile shim behavior
# ---------------------------------------------------------------------------


class TestLazyShimContract:
    """Direct unit-style tests of the lazy primitives. Don't need DB/file store
    but live here so they sit next to the integration tests they guard."""

    def test_no_load_on_construction(self) -> None:
        calls = {"n": 0}

        def loader() -> bytes:
            calls["n"] += 1
            return b"data"

        ChatLoadedFile.lazy_loaded(
            file_id="x",
            file_type=ChatFileType.PLAIN_TEXT,
            filename="x.txt",
            content_text="cached text",
            token_count=3,
            loader=loader,
        )
        assert calls["n"] == 0

    def test_first_access_materializes_once_only(self) -> None:
        calls = {"n": 0}

        def loader() -> bytes:
            calls["n"] += 1
            return b"data"

        f = ChatLoadedFile.lazy_loaded(
            file_id="x",
            file_type=ChatFileType.PLAIN_TEXT,
            filename="x.txt",
            content_text=None,
            token_count=0,
            loader=loader,
        )
        assert f.content == b"data"
        assert f.content == b"data"
        assert calls["n"] == 1

    def test_non_content_attrs_do_not_trigger(self) -> None:
        calls = {"n": 0}
        f = ChatLoadedFile.lazy_loaded(
            file_id="x",
            file_type=ChatFileType.IMAGE,
            filename="x.png",
            content_text=None,
            token_count=0,
            loader=lambda: (calls.__setitem__("n", calls["n"] + 1), b"img")[1],
        )
        _ = f.file_id
        _ = f.filename
        _ = f.file_type
        _ = f.content_text
        _ = f.token_count
        assert calls["n"] == 0

    def test_to_file_descriptor_does_not_materialize(self) -> None:
        calls = {"n": 0}
        f = ChatLoadedFile.lazy_loaded(
            file_id="abc",
            file_type=ChatFileType.PLAIN_TEXT,
            filename="x.txt",
            content_text=None,
            token_count=0,
            loader=lambda: (calls.__setitem__("n", calls["n"] + 1), b"data")[1],
        )
        fd = f.to_file_descriptor()
        assert fd["id"] == "abc"
        assert calls["n"] == 0

    def test_to_base64_materializes_image(self) -> None:
        calls = {"n": 0}
        f = ChatLoadedFile.lazy_loaded(
            file_id="img",
            file_type=ChatFileType.IMAGE,
            filename="x.png",
            content_text=None,
            token_count=0,
            loader=lambda: (calls.__setitem__("n", calls["n"] + 1), b"PNG-bytes")[1],
        )
        _ = f.to_base64()
        assert calls["n"] == 1

    def test_concurrent_first_access_calls_loader_exactly_once(self) -> None:
        """Two threads racing on the first ``.content`` read must not both
        invoke the loader (would be a double S3 GET). The lazy shim takes a
        per-instance ``threading.Lock`` to make check-and-set atomic."""
        import threading

        from onyx.chat.models import ChatLoadedFile

        call_count = {"n": 0}
        gate = threading.Event()

        def slow_loader() -> bytes:
            # Gate guarantees both threads observe _lazy_content_materialized
            # is False before the first writer completes — without the lock,
            # both would enter the load path.
            gate.wait()
            call_count["n"] += 1
            return b"once"

        f = ChatLoadedFile.lazy_loaded(
            file_id="x",
            file_type=ChatFileType.PLAIN_TEXT,
            filename="x.txt",
            content_text=None,
            token_count=0,
            loader=slow_loader,
        )

        results: list[bytes] = []

        def reader() -> None:
            results.append(f.content)

        t1 = threading.Thread(target=reader)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        # Let both threads enter __getattribute__ and contend on the lock.
        gate.set()
        t1.join()
        t2.join()

        assert results == [b"once", b"once"]
        assert call_count["n"] == 1

    def test_chat_file_lazy_content(self) -> None:
        calls = {"n": 0}
        cf = ChatFile.lazy_from_filename(
            filename="x.csv",
            loader=lambda: (calls.__setitem__("n", calls["n"] + 1), b"csv-bytes")[1],
        )
        assert calls["n"] == 0
        _ = cf.filename
        assert calls["n"] == 0
        assert cf.content == b"csv-bytes"
        assert cf.content == b"csv-bytes"
        assert calls["n"] == 1


# ---------------------------------------------------------------------------
# End-to-end via real file_store: load_chat_file / load_all_chat_files
# ---------------------------------------------------------------------------


class TestLoadChatFileLazy:
    def test_load_chat_file_does_not_read_bytes(
        self,
        read_counter: _ReadCounter,
        file_cleanup: list[str],
        db_session: Session,
    ) -> None:
        """``load_chat_file`` must not pull raw bytes from the file store at
        construction. Bytes flow only when ``.content`` is touched."""
        file_id = _write_file(b"sentinel-bytes", file_type="image/png")
        file_cleanup.append(file_id)

        loaded = load_chat_file(
            {"id": file_id, "type": ChatFileType.IMAGE, "name": "icon.png"},
            db_session,
        )

        # Construction must not have read raw bytes.
        assert read_counter.hits_for(file_id) == 0, (
            f"Expected 0 raw reads at construction; got "
            f"{read_counter.hits_for(file_id)}. read_ids={read_counter.read_ids}"
        )

        # First .content access loads.
        assert loaded.content == b"sentinel-bytes"
        assert read_counter.hits_for(file_id) == 1

        # Second access is memoized — no further reads.
        assert loaded.content == b"sentinel-bytes"
        assert read_counter.hits_for(file_id) == 1

    def test_deleted_file_yields_empty_content(
        self,
        read_counter: _ReadCounter,  # noqa: ARG002 — keeps store fixtures live
        db_session: Session,
    ) -> None:
        """A file referenced in chat history but deleted from the file store
        (user-file deletion doesn't scrub chat-message ``files`` references)
        must degrade to empty content on ``.content`` access — not raise and
        kill the send-message flow."""
        file_id = _write_file(b"doomed-bytes", file_type="image/png")

        loaded = load_chat_file(
            {"id": file_id, "type": ChatFileType.IMAGE, "name": "gone.png"},
            db_session,
        )

        # Delete the underlying file after construction but before the lazy
        # bytes read — simulates user-file deletion racing chat history use.
        get_default_file_store().delete_file(file_id)

        assert loaded.content == b""

    def test_transient_read_error_yields_empty_content(
        self,
        read_counter: _ReadCounter,  # noqa: ARG002 — keeps store fixtures live
        file_cleanup: list[str],
        db_session: Session,
    ) -> None:
        """Non-not-found failures (e.g. transient object-store errors) must
        also degrade to empty content rather than raise mid-LLM-flow — the
        send-message request must never die on a history-file read."""
        file_id = _write_file(b"unreachable-bytes", file_type="image/png")
        file_cleanup.append(file_id)

        loaded = load_chat_file(
            {"id": file_id, "type": ChatFileType.IMAGE, "name": "flaky.png"},
            db_session,
        )

        with patch.object(
            file_store_module.S3BackedFileStore,
            "read_file",
            side_effect=ConnectionError("simulated transient store failure"),
        ):
            assert loaded.content == b""


class TestLoadAllChatFilesLazy:
    def test_returns_lazy_files_for_history(
        self,
        read_counter: _ReadCounter,
        file_cleanup: list[str],
        db_session: Session,
    ) -> None:
        """A chat session with N attached files yields N lazy instances and
        triggers zero raw byte reads. The whole point: a heavy history doesn't
        cost a single S3 GET until someone touches ``.content``."""
        user = create_test_user(db_session, f"lazy-load-{uuid4().hex[:8]}")
        chat = create_chat_session(
            db_session=db_session,
            description="lazy",
            user_id=user.id,
            persona_id=None,
        )
        root = get_or_create_root_message(chat.id, db_session)

        parent = root
        file_ids: list[str] = []
        for i in range(10):
            fid = _write_file(f"file-{i}".encode(), file_type="image/png")
            file_ids.append(fid)
            file_cleanup.append(fid)
            parent = create_new_chat_message(
                chat_session_id=chat.id,
                parent_message=parent,
                message=f"msg-{i}",
                token_count=0,
                message_type=MessageType.USER,
                files=[_descriptor(fid, type_=ChatFileType.IMAGE)],
                db_session=db_session,
            )

        # Replay the chat history (skip root) and call the loader.
        chat_history = [
            m for m in db_session.query(type(parent)).filter_by(chat_session_id=chat.id)
        ]
        chat_history = [m for m in chat_history if m.id != root.id]
        assert len(chat_history) == 10

        baseline = read_counter.count
        loaded = load_all_chat_files(chat_history, db_session)
        assert len(loaded) == 10
        # No raw byte reads should have occurred during the load itself.
        assert read_counter.count == baseline, (
            f"load_all_chat_files made {read_counter.count - baseline} raw reads — "
            f"expected 0. ids: {read_counter.read_ids[baseline:]}"
        )

        # Touch one file → exactly one read.
        _ = loaded[0].content
        assert read_counter.count == baseline + 1

    def test_max_workers_capped_at_16(self) -> None:
        """Defense-in-depth: even with 200 files passed in, the thread pool
        is capped at 16 workers."""
        from typing import Any
        from typing import cast

        captured: dict[str, int] = {}

        def _spy(funcs, **kwargs):  # type: ignore[no-untyped-def]
            captured["max_workers"] = kwargs.get("max_workers", -1)
            return [None] * len(funcs)

        with patch(
            "onyx.chat.chat_utils.run_functions_tuples_in_parallel", side_effect=_spy
        ):
            # Synthetic 200-file "message" — we patch the parallel runner so
            # actual DB/file_store access never happens. Casting through Any
            # bypasses the ORM type contract that is irrelevant for this
            # particular invariant check.
            class _FakeMsg:
                files = [
                    {
                        "id": f"id-{i}",
                        "type": ChatFileType.PLAIN_TEXT,
                        "name": f"f-{i}.txt",
                    }
                    for i in range(200)
                ]

            from onyx.chat.chat_utils import load_all_chat_files as _llc

            _llc(cast(Any, [_FakeMsg()]), cast(Any, None))
            assert captured["max_workers"] == 16


# ---------------------------------------------------------------------------
# process_message-layer consumers
# ---------------------------------------------------------------------------


class TestConvertLoadedFilesToChatFilesLazy:
    """``_convert_loaded_files_to_chat_files`` must produce lazy ChatFiles —
    it must not call ``len(loaded_file.content) > 0`` style guards that
    would defeat the lazy fix."""

    def test_wrapping_does_not_materialize(
        self,
        read_counter: _ReadCounter,
        file_cleanup: list[str],
        db_session: Session,
    ) -> None:
        from onyx.chat.process_message import _convert_loaded_files_to_chat_files

        file_id = _write_file(b"some-bytes", file_type="image/png")
        file_cleanup.append(file_id)
        loaded = [
            load_chat_file(
                {"id": file_id, "type": ChatFileType.IMAGE, "name": "x.png"},
                db_session,
            )
        ]

        baseline = read_counter.count
        chat_files = _convert_loaded_files_to_chat_files(loaded)
        assert len(chat_files) == 1
        # Wrapping must not have materialized anything.
        assert read_counter.count == baseline

        # And the wrapped ChatFile, when materialized, pulls exactly once.
        assert chat_files[0].content == b"some-bytes"
        assert read_counter.count == baseline + 1
