"""Guards the incognito recording policy: no mode other than FULL_HISTORY may
write conversation content, a corrupt mode value reads as the safe one, and a
content-free turn's persisted file descriptors keep linkage but not names.
"""

from onyx.chat.incognito import (
    content_free_file_descriptors,
    resolve_incognito_record_mode,
)
from onyx.db.enums import IncognitoRecordMode
from onyx.file_store.models import ChatFileType, FileDescriptor


def test_only_full_history_persists_content() -> None:
    persisting = [m for m in IncognitoRecordMode if m.persists_content]
    assert persisting == [IncognitoRecordMode.FULL_HISTORY]


def test_default_never_persists_content() -> None:
    """A dropped admin setting must not silently start recording chats."""
    assert resolve_incognito_record_mode() is IncognitoRecordMode.USAGE_ONLY
    assert resolve_incognito_record_mode().persists_content is False


def test_unknown_context_value_fails_closed() -> None:
    """A corrupt contextvar must never read as content-persisting."""
    assert IncognitoRecordMode.from_context_value("garbage") is (
        IncognitoRecordMode.USAGE_ONLY
    )
    assert IncognitoRecordMode.from_context_value(None) is None


def test_descriptors_strip_the_name_and_keep_linkage() -> None:
    scrubbed = content_free_file_descriptors(
        [
            FileDescriptor(
                id="file-1",
                type=ChatFileType.DOC,
                name="acquisition_target.pdf",
                user_file_id="uf-1",
            )
        ]
    )
    assert scrubbed == [
        FileDescriptor(id="file-1", type=ChatFileType.DOC, user_file_id="uf-1")
    ]
    assert "name" not in scrubbed[0]
