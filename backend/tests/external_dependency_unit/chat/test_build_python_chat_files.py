"""External-dependency tests for `build_python_chat_files_from_search_docs`.

This is the staging step that turns connector-file-bearing search hits into
`ChatFile`s for the Python code interpreter. Uses real Postgres + real file
store because the function reads bytes + file_records from the store, and
mocking those would obscure the origin-allowlist + metadata plumbing that
are the whole point.
"""

from collections.abc import Generator
from io import BytesIO
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.chat.chat_utils import build_python_chat_files_from_search_docs
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.context.search.models import SearchDoc
from onyx.file_store.file_store import get_default_file_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_search_doc(
    *,
    file_id: str | None,
    semantic_identifier: str,
    document_id: str | None = None,
) -> SearchDoc:
    return SearchDoc(
        document_id=document_id or f"doc-{uuid4().hex[:8]}",
        chunk_ind=0,
        semantic_identifier=semantic_identifier,
        link=None,
        blurb="",
        source_type=DocumentSource.MOCK_CONNECTOR,
        boost=1,
        hidden=False,
        metadata={},
        score=0.5,
        match_highlights=[],
        file_id=file_id,
    )


def _write_file(
    content: bytes,
    *,
    origin: FileOrigin = FileOrigin.CONNECTOR,
) -> str:
    return get_default_file_store().save_file(
        content=BytesIO(content),
        display_name=None,
        file_origin=origin,
        file_type="text/csv",
        file_metadata={"test": True},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def file_cleanup(
    db_session: Session,  # noqa: ARG001 — keeps tenant context alive for file_store
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
) -> Generator[list[str], None, None]:
    """Track file_ids written by the test so teardown reaps them."""
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


class TestBuildPythonChatFiles:
    def test_empty_input_returns_empty(
        self,
        file_cleanup: list[str],  # noqa: ARG002 — keeps tenant + store fixtures alive
    ) -> None:
        assert build_python_chat_files_from_search_docs([]) == []

    def test_docs_without_file_id_return_empty(
        self,
        file_cleanup: list[str],  # noqa: ARG002
    ) -> None:
        docs = [
            _make_search_doc(file_id=None, semantic_identifier="no-file.pdf"),
            _make_search_doc(file_id=None, semantic_identifier="also-none"),
        ]
        assert build_python_chat_files_from_search_docs(docs) == []

    def test_connector_origin_file_is_staged(
        self,
        file_cleanup: list[str],
    ) -> None:
        file_id = _write_file(b"hello,world\n1,2\n")
        file_cleanup.append(file_id)

        docs = [
            _make_search_doc(file_id=file_id, semantic_identifier="greetings.csv"),
        ]

        chat_files = build_python_chat_files_from_search_docs(docs)

        assert len(chat_files) == 1
        assert chat_files[0].filename == f"greetings_{file_id}.csv"
        assert chat_files[0].content == b"hello,world\n1,2\n"

    def test_disallowed_origin_is_rejected(
        self,
        file_cleanup: list[str],
    ) -> None:
        """Only `CONNECTOR`-origin files are eligible via this path —
        `CHAT_UPLOAD` and others use different pipelines and must not leak
        through even if a SearchDoc happens to reference their file_id."""
        file_id = _write_file(b"from chat", origin=FileOrigin.CHAT_UPLOAD)
        file_cleanup.append(file_id)

        docs = [_make_search_doc(file_id=file_id, semantic_identifier="usr-upload.txt")]

        assert build_python_chat_files_from_search_docs(docs) == []

    def test_unknown_file_id_is_silently_dropped(
        self,
        file_cleanup: list[str],  # noqa: ARG002
    ) -> None:
        """Bad/stale file_id → log warning, skip it, continue the batch."""
        docs = [
            _make_search_doc(
                file_id="does-not-exist", semantic_identifier="missing.csv"
            )
        ]
        assert build_python_chat_files_from_search_docs(docs) == []

    def test_mixed_good_and_bad_entries_return_only_good(
        self,
        file_cleanup: list[str],
    ) -> None:
        good_id = _write_file(b"ok")
        blocked_id = _write_file(b"nope", origin=FileOrigin.CHAT_UPLOAD)
        file_cleanup.extend([good_id, blocked_id])

        docs = [
            _make_search_doc(file_id=good_id, semantic_identifier="ok.csv"),
            _make_search_doc(file_id=blocked_id, semantic_identifier="blocked.csv"),
            _make_search_doc(file_id="ghost", semantic_identifier="ghost.csv"),
            _make_search_doc(file_id=None, semantic_identifier="no-id.csv"),
        ]

        chat_files = build_python_chat_files_from_search_docs(docs)

        assert [cf.filename for cf in chat_files] == [f"ok_{good_id}.csv"]

    def test_duplicate_file_ids_deduped_first_hit_wins(
        self,
        file_cleanup: list[str],
    ) -> None:
        """Repeated hits for the same doc only ship one ChatFile, and the
        filename comes from the FIRST hit's semantic_identifier."""
        file_id = _write_file(b"single copy")
        file_cleanup.append(file_id)

        docs = [
            _make_search_doc(file_id=file_id, semantic_identifier="first.csv"),
            _make_search_doc(
                file_id=file_id, semantic_identifier="second-name-ignored.csv"
            ),
            _make_search_doc(file_id=file_id, semantic_identifier="third-ignored.csv"),
        ]

        chat_files = build_python_chat_files_from_search_docs(docs)

        assert len(chat_files) == 1
        assert chat_files[0].filename == f"first_{file_id}.csv"

    def test_distinct_file_ids_with_same_title_get_distinct_names(
        self,
        file_cleanup: list[str],
    ) -> None:
        """Two distinct file_ids with IDENTICAL titles must each get a unique
        sandbox filename — file_id is embedded in the filename so collisions
        are impossible by construction."""
        file_a = _write_file(b"first")
        file_b = _write_file(b"second")
        file_c = _write_file(b"third")
        file_cleanup.extend([file_a, file_b, file_c])

        docs = [
            _make_search_doc(file_id=file_a, semantic_identifier="Report.pdf"),
            _make_search_doc(file_id=file_b, semantic_identifier="Report.pdf"),
            _make_search_doc(file_id=file_c, semantic_identifier="Report.pdf"),
        ]

        chat_files = build_python_chat_files_from_search_docs(docs)

        assert [cf.filename for cf in chat_files] == [
            f"Report_{file_a}.pdf",
            f"Report_{file_b}.pdf",
            f"Report_{file_c}.pdf",
        ]
        assert chat_files[0].content == b"first"
        assert chat_files[1].content == b"second"
        assert chat_files[2].content == b"third"

    def test_title_sanitization_applied_to_filename(
        self,
        file_cleanup: list[str],
    ) -> None:
        file_id = _write_file(b"payload")
        file_cleanup.append(file_id)

        docs = [_make_search_doc(file_id=file_id, semantic_identifier="Q1/Q2 Report")]

        chat_files = build_python_chat_files_from_search_docs(docs)

        assert len(chat_files) == 1
        assert chat_files[0].filename == f"Q1_Q2 Report_{file_id}"

    def test_original_order_preserved(
        self,
        file_cleanup: list[str],
    ) -> None:
        """Output order follows the input SearchDoc order."""
        ids = [_write_file(f"body-{i}".encode()) for i in range(3)]
        file_cleanup.extend(ids)

        docs = [
            _make_search_doc(file_id=ids[0], semantic_identifier="a.csv"),
            _make_search_doc(file_id=ids[1], semantic_identifier="b.csv"),
            _make_search_doc(file_id=ids[2], semantic_identifier="c.csv"),
        ]

        chat_files = build_python_chat_files_from_search_docs(docs)

        assert [cf.filename for cf in chat_files] == [
            f"a_{ids[0]}.csv",
            f"b_{ids[1]}.csv",
            f"c_{ids[2]}.csv",
        ]
