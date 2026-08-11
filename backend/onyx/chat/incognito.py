"""Recording policy for incognito chat turns.

An incognito chat is an ordinary chat carrying a mode. ``IncognitoRecordMode``
is the only policy object: behavior is exposed as derived properties on it, so
the legal states are the only representable ones and no caller can assemble an
illegal combination out of loose booleans.

The contract that enforcement points must honor: an incognito session must pin
its mode on a metadata-only ``chat_session`` row at creation, and downstream
code must read the pinned value, never the live admin setting, so a setting
change cannot alter a session under way. Only FULL_HISTORY may write
``chat_message`` rows. USAGE_ONLY must carry the live conversation outside
Postgres for the length of the session.
"""

from onyx.db.enums import IncognitoRecordMode


def resolve_incognito_record_mode() -> IncognitoRecordMode:
    """The mode a new incognito session must pin.

    The seam a workspace's record-mode setting must resolve through. Today it
    returns the default unconditionally.
    """
    return IncognitoRecordMode.USAGE_ONLY
