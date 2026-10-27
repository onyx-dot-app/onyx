"""History attachment loading must not share the caller's database session."""

from io import BytesIO
from threading import get_ident
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.chat.chat_utils import load_all_chat_files
from onyx.db.enums import UserFileStatus
from onyx.db.models import ChatMessage, UserFile
from onyx.file_store.models import ChatFileType, FileDescriptor


def test_attachment_metadata_is_read_before_workers() -> None:
    caller_thread = get_ident()
    session = MagicMock(spec=Session)
    file_ids = [uuid4(), uuid4()]
    metadata_reads: list[UUID | str] = []
    descriptors: list[FileDescriptor] = [
        {
            "id": str(file_id),
            "type": ChatFileType.PLAIN_TEXT,
            "user_file_id": str(file_id),
        }
        for file_id in file_ids
    ]

    def get_metadata(user_file_id: UUID | str, db_session: Session) -> UserFile:
        assert get_ident() == caller_thread
        assert db_session is session
        metadata_reads.append(user_file_id)
        return UserFile(token_count=17, status=UserFileStatus.COMPLETED)

    def read_plaintext(*_args: object, **_kwargs: object) -> str:
        assert get_ident() != caller_thread
        assert metadata_reads == file_ids
        return "cached text"

    with (
        patch("onyx.chat.chat_utils.get_user_file_by_id", side_effect=get_metadata),
        patch(
            "onyx.chat.chat_utils._get_or_extract_plaintext", side_effect=read_plaintext
        ),
        patch("onyx.chat.chat_utils.get_default_file_store") as store,
    ):
        loaded = load_all_chat_files([ChatMessage(files=descriptors)], session)
        assert [file.file_id for file in loaded] == [
            str(file_id) for file_id in file_ids
        ]
        assert [file.token_count for file in loaded] == [17, 17]
        assert [file.content_text for file in loaded] == ["cached text", "cached text"]
        store.assert_not_called()
        store.return_value.read_file.return_value = BytesIO(b"raw")
        assert loaded[0].content == b"raw"
        store.return_value.read_file.assert_called_once()


@pytest.mark.parametrize("status", [None, *UserFileStatus])
def test_loading_preserves_processing_plaintext_guard(
    status: UserFileStatus | None,
) -> None:
    user_file_id = str(uuid4())
    descriptor: FileDescriptor = {
        "id": "storage-id",
        "type": ChatFileType.PLAIN_TEXT,
        "user_file_id": user_file_id,
    }
    user_file = UserFile(token_count=None, status=status) if status else None
    session = MagicMock(spec=Session)
    pending = status in (UserFileStatus.PROCESSING, UserFileStatus.INDEXING)
    with (
        patch("onyx.chat.chat_utils.get_user_file_by_id", return_value=user_file),
        patch(
            "onyx.chat.chat_utils._get_or_extract_plaintext", return_value="text"
        ) as plaintext,
    ):
        loaded = load_all_chat_files([ChatMessage(files=[descriptor])], session)[0]
    assert loaded.token_count == 0
    assert loaded.content_pending is pending
    assert plaintext.call_args.args[0] == user_file_id
    assert plaintext.call_args.kwargs["store_on_miss"] is not pending


@pytest.mark.parametrize("user_file_id", [None, "not-a-uuid"])
def test_history_without_valid_user_file_id_keeps_lazy_image(
    user_file_id: str | None,
) -> None:
    descriptor: FileDescriptor = {"id": "generated-image", "type": ChatFileType.IMAGE}
    if user_file_id is not None:
        descriptor["user_file_id"] = user_file_id
    with (
        patch("onyx.chat.chat_utils.get_user_file_by_id") as lookup,
        patch("onyx.chat.chat_utils.get_default_file_store") as store,
    ):
        loaded = load_all_chat_files(
            [ChatMessage(files=[descriptor])], MagicMock(spec=Session)
        )
    lookup.assert_not_called()
    store.assert_not_called()
    assert loaded[0].token_count == 0
    assert not loaded[0].content_pending
