"""External-dependency tests for `build_python_chat_files_from_search_docs`.

This is the staging step that turns the files of search results into
`ChatFile`s for the Python code interpreter, under the names that the results
give them. Uses real Postgres + real file store because the function reads
bytes from the store.
"""

from collections.abc import Generator
from io import BytesIO

import pytest
from sqlalchemy.orm import Session

from onyx.chat.files import build_python_chat_files_from_search_docs
from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.sandbox.harness_base import search_file_name

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
        assert build_python_chat_files_from_search_docs({}) == []

    def test_connector_origin_file_is_staged_under_its_name(
        self,
        file_cleanup: list[str],
    ) -> None:
        file_id = _write_file(b"hello,world\n1,2\n")
        file_cleanup.append(file_id)
        name = search_file_name(file_id, "greetings.csv")

        chat_files = build_python_chat_files_from_search_docs({file_id: name})

        assert len(chat_files) == 1
        assert chat_files[0].filename == name
        assert chat_files[0].file_id == file_id
        assert chat_files[0].content == b"hello,world\n1,2\n"

    def test_original_order_preserved(
        self,
        file_cleanup: list[str],
    ) -> None:
        """Output order follows the input order."""
        ids = [_write_file(f"body-{i}".encode()) for i in range(3)]
        file_cleanup.extend(ids)
        names = {
            file_id: search_file_name(file_id, title)
            for file_id, title in zip(ids, ("a.csv", "b.csv", "c.csv"), strict=True)
        }

        chat_files = build_python_chat_files_from_search_docs(names)

        assert [(cf.file_id, cf.filename) for cf in chat_files] == list(names.items())
        assert [cf.content for cf in chat_files] == [b"body-0", b"body-1", b"body-2"]
