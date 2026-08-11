"""Recording policy for incognito chat turns.

An incognito chat is an ordinary chat carrying a mode. ``IncognitoRecordMode``
is the only policy object: behavior is exposed as derived properties on it, so
the legal states are the only representable ones and no caller can assemble an
illegal combination out of loose booleans.

The contract that enforcement points must honor: an incognito session must pin
its mode on a metadata-only ``chat_session`` row at creation, and downstream
code must read the pinned value, never the live admin setting, so a setting
change cannot alter a session under way. Only FULL_HISTORY may write
conversation content into ``chat_message`` rows. USAGE_ONLY writes
content-free rows and must carry the live conversation outside Postgres
for the length of the session.
"""

from onyx.db.enums import IncognitoRecordMode
from onyx.file_store.models import FileDescriptor


def resolve_incognito_record_mode() -> IncognitoRecordMode:
    """The mode a new incognito session must pin.

    The seam a workspace's record-mode setting must resolve through. Today it
    returns the default unconditionally.
    """
    return IncognitoRecordMode.USAGE_ONLY


def content_free_file_descriptors(
    file_descriptors: list[FileDescriptor],
) -> list[FileDescriptor]:
    """Descriptors safe to persist for a content-free turn. Linkage ids and
    type survive for the file-reader tool and teardown. The content-derived
    filename does not."""
    return [
        FileDescriptor(
            id=fd["id"], type=fd["type"], user_file_id=fd.get("user_file_id")
        )
        for fd in file_descriptors
    ]
