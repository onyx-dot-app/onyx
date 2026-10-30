"""Replay cursors retain an exact prefix while cache writes continue."""

import json
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from onyx.chat.stream_buffer import (
    StreamBufferMeta,
    StreamBufferWriter,
    StreamChunkRead,
    _meta_key,
)
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.query_and_chat import chat_backend
from tests.unit.fakes import FakeCache


@pytest.mark.parametrize(("initial_chunks", "cursor"), [(0, 0), (3, 0), (3, 2), (3, 3)])
def test_resume_freezes_backlog_boundary_and_returns_cursors(
    initial_chunks: int, cursor: int
) -> None:
    cache = FakeCache()
    session_id = uuid4()
    writer = StreamBufferWriter(cache, session_id, 42)
    for index in range(initial_chunks):
        writer.append_line(json.dumps({"content": str(index)}) + "\n")
        writer.flush()
    if not initial_chunks:
        cache.set(_meta_key(session_id, 42), StreamBufferMeta().model_dump_json())
    original_read = chat_backend.read_stream_chunks

    def read_with_concurrent_write(
        cache: FakeCache,
        chat_session_id: UUID,
        stream_id: int,
        cursor: int,
        *,
        max_chunks: int | None = None,
    ) -> StreamChunkRead | None:
        read = original_read(
            cache, chat_session_id, stream_id, cursor, max_chunks=max_chunks
        )
        if read is not None and read.chunk_count == initial_chunks:
            writer.append_line('{"content":"live"}\n')
            writer.mark_done()
        return read

    app = FastAPI()

    @app.get("/resume")
    def resume() -> StreamingResponse:
        return chat_backend.resume_chat_stream(
            session_id, cursor=cursor, expected_stream_id=42, user=User(id=uuid4())
        )

    with (
        patch.object(chat_backend, "get_session_with_current_tenant"),
        patch.object(chat_backend, "get_chat_session_by_id"),
        patch.object(chat_backend, "get_cache_backend", return_value=cache),
        patch.object(chat_backend, "get_processing_stream_id", return_value=42),
        patch.object(chat_backend, "_RESUME_MAX_CHUNKS_PER_READ", 1),
        patch.object(
            chat_backend, "read_stream_chunks", side_effect=read_with_concurrent_write
        ),
        TestClient(app) as client,
    ):
        response = client.get("/resume")
    assert response.status_code == 200
    records = [json.loads(line) for line in response.text.splitlines()]
    contents = [record["content"] for record in records if "content" in record]
    assert contents == [str(index) for index in range(cursor, initial_chunks)] + [
        "live"
    ]
    checkpoints = [record for record in records if "next_cursor" in record]
    assert checkpoints[-1] == {
        "stream_id": 42,
        "next_cursor": initial_chunks + 1,
        "replay_complete": True,
    }
    restored = next(record for record in checkpoints if record["replay_complete"])
    assert restored["next_cursor"] == initial_chunks
    live_index = records.index({"content": "live"})
    assert records.index(restored) < live_index


def test_resume_rejects_cursor_for_a_different_stream() -> None:
    with (
        patch.object(chat_backend, "get_session_with_current_tenant"),
        patch.object(chat_backend, "get_chat_session_by_id"),
        patch.object(chat_backend, "get_cache_backend", return_value=FakeCache()),
        patch.object(chat_backend, "get_processing_stream_id", return_value=43),
        patch.object(chat_backend, "read_stream_chunks") as read,
        pytest.raises(OnyxError, match="No resumable stream"),
    ):
        chat_backend.resume_chat_stream(
            uuid4(), cursor=2, expected_stream_id=42, user=User(id=uuid4())
        )
    read.assert_not_called()
