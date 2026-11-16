"""Check metadata ownership and concurrent content loading without a live store."""

from io import BytesIO
from threading import Barrier, Lock, get_ident
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from onyx.db.models import UserFile
from onyx.db.user_file import capture_user_file_metadata, get_user_file_metadata
from onyx.file_store.models import ChatFileType
from onyx.file_store.utils import load_in_memory_chat_files
from onyx.tools.tool_implementations.file_reader.file_reader_tool import FileReaderTool


def test_parallel_content_reads_use_snapshots_after_session_close() -> None:
    files = [
        UserFile(
            id=uuid4(),
            file_id=f"file-{index}",
            name=f"{index}.txt",
            file_type="text/plain",
            token_count=index,
        )
        for index in range(2)
    ]
    with Session(close_resets_only=False) as session:
        session.add_all(files)
        metadata = capture_user_file_metadata(files)
    assert all(inspect(file).session is None for file in files)
    files[0].name = "changed.txt"
    with pytest.raises(ValidationError, match="frozen"):
        metadata[0].__setattr__("name", "changed.txt")

    barrier = Barrier(2, timeout=5)
    lock = Lock()
    readers: set[int] = set()

    def read_file(file_id: str, *, mode: str) -> BytesIO:
        assert mode == "b"
        assert all(inspect(file).session is None for file in files)
        with lock:
            readers.add(get_ident())
        barrier.wait()
        return BytesIO(file_id.encode())

    store = MagicMock()
    store.read_file_record.return_value.file_type = "text/plain"
    store.read_file.side_effect = read_file
    with patch("onyx.file_store.utils.get_default_file_store", return_value=store):
        loaded = load_in_memory_chat_files(metadata)
    assert len(readers) == 2
    assert [file.filename for file in loaded] == ["0.txt", "1.txt"]
    assert [file.content for file in loaded] == [
        f"plaintext_{file.id}".encode() for file in metadata
    ]
    assert all(file.file_type == ChatFileType.PLAIN_TEXT for file in loaded)


def test_missing_user_file_fails_before_content_loading() -> None:
    file_id = uuid4()
    with patch("onyx.db.user_file.get_user_file_by_id", return_value=None):
        with pytest.raises(ValueError, match=f"User file with id {file_id} not found"):
            get_user_file_metadata(file_id, MagicMock(spec=Session))


def test_file_reader_closes_metadata_session_before_store_reads() -> None:
    file = UserFile(
        id=uuid4(),
        file_id="stored-file",
        name="file.txt",
        file_type="text/plain",
        token_count=3,
    )
    context = MagicMock()
    store = MagicMock()

    def record(file_id: str) -> MagicMock:
        context.__exit__.assert_called_once()
        assert file_id == "stored-file"
        return MagicMock(file_type="text/plain")

    store.read_file_record.side_effect = record
    store.read_file.return_value = BytesIO(b"content")
    module = "onyx.tools.tool_implementations.file_reader.file_reader_tool"
    with (
        patch(f"{module}.get_session_with_current_tenant", return_value=context),
        patch("onyx.db.user_file.get_user_file_by_id", return_value=file),
        patch("onyx.file_store.utils.get_default_file_store", return_value=store),
    ):
        tool = FileReaderTool(
            tool_id=99,
            user_file_ids=[file.id],
            chat_file_ids=[],
        )
        assert tool._load_file(file.id).content == b"content"
