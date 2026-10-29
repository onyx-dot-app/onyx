"""Checkpoint file values preserve bytes and defer stored file reads."""

import pytest

from onyx.chat.response_models import ChatSearchResult
from onyx.file_store.models import ChatFileType, ChatLoadedFile, ExtractedContextFiles
from onyx.tools.file_snapshot import SavedChatFile, SavedContextFiles
from onyx.tools.models import ChatFile


def test_binary_staged_files_round_trip_in_search_payload() -> None:
    original = ChatSearchResult(
        search_docs=[],
        citation_mapping={},
        staged_files=[ChatFile(filename="image.png", content=b"\xff\x00\x80")],
    )
    restored = ChatSearchResult.model_validate_json(original.model_dump_json())
    assert restored.staged_files[0].content == b"\xff\x00\x80"
    assert restored.staged_files[0].filename == "image.png"


def test_snapshot_keeps_lazy_reference_without_reading_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads: list[str] = []

    def read(file_id: str) -> bytes:
        reads.append(file_id)
        return b"stored bytes"

    monkeypatch.setattr("onyx.tools.file_snapshot.read_checkpoint_file", read)
    original = ChatFile.lazy_from_filename(
        filename="document.txt", file_id="stored-id", loader=lambda: read("original")
    )
    saved = SavedChatFile.capture(original)
    restored = SavedChatFile.model_validate_json(saved.model_dump_json()).restore()
    assert reads == []
    assert saved.content is None
    assert restored.file_id == "stored-id"
    assert restored.content == b"stored bytes"
    assert restored.content == b"stored bytes"
    assert reads == ["stored-id"]


def test_context_images_keep_metadata_and_lazy_storage_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads: list[str] = []

    def read(file_id: str) -> bytes:
        reads.append(file_id)
        return b"\xff\x00"

    monkeypatch.setattr("onyx.tools.file_snapshot.read_checkpoint_file", read)
    image = ChatLoadedFile.lazy_loaded(
        file_id="image-id",
        file_type=ChatFileType.IMAGE,
        filename="image.png",
        content_text=None,
        token_count=12,
        loader=lambda: read("original"),
    )
    original = ExtractedContextFiles(
        file_texts=["included context"],
        image_files=[image],
        use_as_search_filter=False,
        total_token_count=15,
        file_metadata=[],
        uncapped_token_count=15,
    )
    saved = SavedContextFiles.capture(original)
    restored = SavedContextFiles.model_validate_json(saved.model_dump_json()).restore()
    assert reads == []
    assert len(original.image_files) == 1
    assert restored.file_texts == ["included context"]
    assert restored.image_files[0].token_count == 12
    assert restored.image_files[0].content == b"\xff\x00"
    assert reads == ["image-id"]


def test_file_without_contents_or_reference_cannot_restore() -> None:
    with pytest.raises(ValueError, match="neither content nor a stored reference"):
        SavedChatFile(filename="missing").restore()
