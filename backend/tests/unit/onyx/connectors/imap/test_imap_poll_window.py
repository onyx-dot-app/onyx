import re
import time
from datetime import datetime, timezone

import pytest

from onyx.connectors.imap.connector import (
    _fetch_email_ids_in_mailbox,
    _parse_internaldate_line,
)


class _FakeImapServer:
    """Follows RFC 3501: SEARCH compares the INTERNALDATE calendar date in the
    message's own timezone, and FETCH returns the exact INTERNALDATE."""

    def __init__(self, internal_dates: list[str]) -> None:
        self._dates = [datetime.fromisoformat(d) for d in internal_dates]

    def select(self, **_kwargs: object) -> tuple[str, list[bytes]]:
        return "OK", [str(len(self._dates)).encode()]

    def search(self, _charset: None, criteria: str) -> tuple[str, list[bytes]]:
        since_str, before_str = re.findall(r'"([^"]+)"', criteria)
        since = datetime.strptime(since_str, "%d-%b-%Y").date()
        before = datetime.strptime(before_str, "%d-%b-%Y").date()
        ids = [
            str(seq)
            for seq, internal_date in enumerate(self._dates, start=1)
            if since <= internal_date.date() < before
        ]
        return "OK", [" ".join(ids).encode()]

    def fetch(self, message_set: str, message_parts: str) -> tuple[str, list[bytes]]:
        if message_parts != "(INTERNALDATE)":
            raise AssertionError(f"unexpected fetch {message_parts=}")
        lines = []
        for seq in message_set.split(","):
            internal_date = self._dates[int(seq) - 1]
            lines.append(
                f'{seq} (INTERNALDATE "{internal_date.strftime("%d-%b-%Y %H:%M:%S %z")}")'.encode()
            )
        return "OK", lines


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso).astimezone(timezone.utc).timestamp()


@pytest.mark.parametrize(
    "start,end,internal_dates,expected_ids",
    [
        pytest.param(
            "2026-10-09T10:00:00+00:00",
            "2026-10-09T10:05:00+00:00",
            [
                "2026-10-09T09:59:59+00:00",
                "2026-10-09T10:02:00+00:00",
                "2026-10-09T10:05:00+00:00",
            ],
            ["2"],
            id="todays-mail-in-window",
        ),
        pytest.param(
            "1970-01-01T00:00:00+00:00",
            "2026-10-09T10:05:00+00:00",
            ["2026-10-08T23:59:00+00:00", "2026-10-09T10:02:00+00:00"],
            ["1", "2"],
            id="initial-load-includes-today",
        ),
        pytest.param(
            "2026-10-08T23:30:00+00:00",
            "2026-10-09T00:05:00+00:00",
            ["2026-10-08T23:45:00+00:00", "2026-10-09T00:02:00+00:00"],
            ["1", "2"],
            id="cross-midnight",
        ),
        pytest.param(
            "2026-12-31T23:00:00+00:00",
            "2027-01-01T00:00:00+00:00",
            ["2026-12-31T23:30:00+00:00", "2027-01-01T00:00:00+00:00"],
            ["1"],
            id="year-rollover-exclusive-end",
        ),
        pytest.param(
            # The server stores +08:00 dates, so the SEARCH date is a day ahead of UTC.
            "2026-10-09T20:00:00+00:00",
            "2026-10-09T21:00:00+00:00",
            ["2026-10-10T04:30:00+08:00"],
            ["1"],
            id="server-timezone-ahead-of-utc",
        ),
        pytest.param(
            "2026-10-09T05:00:00+00:00",
            "2026-10-09T06:00:00+00:00",
            ["2026-10-08T22:30:00-07:00"],
            ["1"],
            id="server-timezone-behind-utc",
        ),
    ],
)
def test_poll_window_uses_exact_internaldate(
    start: str, end: str, internal_dates: list[str], expected_ids: list[str]
) -> None:
    server = _FakeImapServer(internal_dates)

    ids = _fetch_email_ids_in_mailbox(
        mail_client=server,  # ty: ignore[invalid-argument-type]
        mailbox="INBOX",
        start=_ts(start),
        end=_ts(end),
    )

    assert ids == expected_ids


def test_consecutive_polls_neither_skip_nor_repeat() -> None:
    internal_dates = [
        "2026-10-09T23:58:00+00:00",
        "2026-10-10T00:00:00+00:00",
        "2026-10-10T00:03:00+00:00",
        "2026-10-10T00:10:00+00:00",
    ]
    boundaries = [
        "2026-10-09T23:55:00+00:00",
        "2026-10-10T00:00:00+00:00",
        "2026-10-10T00:05:00+00:00",
        "2026-10-10T00:15:00+00:00",
    ]
    fetched: list[str] = []
    for window_start, window_end in zip(boundaries, boundaries[1:], strict=False):
        fetched += _fetch_email_ids_in_mailbox(
            mail_client=_FakeImapServer(internal_dates),  # ty: ignore[invalid-argument-type]
            mailbox="INBOX",
            start=_ts(window_start),
            end=_ts(window_end),
        )

    assert fetched == ["1", "2", "3", "4"]


def test_parse_internaldate_line_handles_space_padded_day() -> None:
    assert _parse_internaldate_line(
        b'7 (INTERNALDATE " 9-Oct-2026 10:02:00 +0200")'
    ) == (
        "7",
        _ts("2026-10-09T10:02:00+02:00"),
    )


@pytest.mark.parametrize(
    "line",
    [
        '7 (INTERNALDATE "31-Feb-2026 10:02:00 +0000")',
        '7 (INTERNALDATE "09-Oct-2026 10:02:00 +9900")',
        '7 (INTERNALDATE "09-Oct-2026 10:02:00 +0099")',
        '7 (INTERNALDATE "09-Xyz-2026 10:02:00 +0000")',
    ],
)
def test_invalid_internaldate_is_unknown_and_message_is_kept(line: str) -> None:
    assert _parse_internaldate_line(line.encode()) is None

    class _BadDateServer(_FakeImapServer):
        def fetch(
            self,
            message_set: str,
            message_parts: str,  # noqa: ARG002 - matches the fetch signature
        ) -> tuple[str, list[bytes]]:
            return "OK", [line.replace("7", message_set, 1).encode()]

    ids = _fetch_email_ids_in_mailbox(
        mail_client=_BadDateServer(["2026-10-09T10:02:00+00:00"]),  # ty: ignore[invalid-argument-type]
        mailbox="INBOX",
        start=_ts("2026-10-09T10:00:00+00:00"),
        end=_ts("2026-10-09T10:05:00+00:00"),
    )

    assert ids == ["1"]


@pytest.mark.parametrize(
    "internal_date", ["01-Nov-2026 08:30:00 +0000", "01-Nov-2026 09:30:00 +0000"]
)
def test_internaldate_is_exact_across_local_dst_fallback(
    monkeypatch: pytest.MonkeyPatch, internal_date: str
) -> None:
    # 01:30 local happens twice in America/Los_Angeles on this date.
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    try:
        parsed = _parse_internaldate_line(
            f'3 (INTERNALDATE "{internal_date}")'.encode()
        )
    finally:
        monkeypatch.undo()
        time.tzset()

    expected = datetime.strptime(internal_date, "%d-%b-%Y %H:%M:%S %z").timestamp()
    assert parsed == ("3", expected)
