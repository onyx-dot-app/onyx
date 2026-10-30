"""present_index_content_hash: which stored hash describes the PRESENT index."""

import pytest

from onyx.db.document import PresentSearchSettingsRef, present_index_content_hash
from onyx.db.models import Document

PRESENT = 10
PIN = 9  # the INSTANT backfill source
OLDER = 8
NEWER = 11

PLAIN = PresentSearchSettingsRef(id=PRESENT, port_backfill_source_id=None)
PINNED = PresentSearchSettingsRef(id=PRESENT, port_backfill_source_id=PIN)


def _row(content_hash: str | None, record: tuple[str | None, int] | None) -> Document:
    recorded_hash, recorded_for = record or (None, None)
    return Document(
        id="d",
        semantic_id="d",
        content_hash=content_hash,
        secondary_content_hash=recorded_hash,
        secondary_search_settings_id=recorded_for,
    )


@pytest.mark.parametrize(
    ("present", "content_hash", "record", "expected"),
    [
        # nothing recorded (row from before the columns existed): content_hash
        (PLAIN, "c", None, "c"),
        (PLAIN, None, None, None),
        # recorded for PRESENT: the record wins over a stale content_hash
        (PLAIN, "stale", ("r", PRESENT), "r"),
        (PLAIN, "c", (None, PRESENT), None),
        # recorded for the INSTANT backfill source, which brings that version
        (PINNED, "c", ("r", PIN), "r"),
        (PLAIN, "c", ("r", PIN), None),
        # recorded for a FUTURE index, which copied the PRESENT hash into content_hash
        (PLAIN, "c", ("r", NEWER), "c"),
        # recorded for an older index: the doc never reached PRESENT
        (PLAIN, "c", ("r", OLDER), None),
    ],
    ids=[
        "no-record-hash",
        "no-record-none",
        "recorded-for-present",
        "recorded-for-present-none",
        "recorded-for-pin",
        "recorded-for-pin-without-pin-is-older",
        "recorded-for-newer",
        "recorded-for-older",
    ],
)
def test_present_index_content_hash(
    present: PresentSearchSettingsRef,
    content_hash: str | None,
    record: tuple[str | None, int] | None,
    expected: str | None,
) -> None:
    assert present_index_content_hash(_row(content_hash, record), present) == expected
