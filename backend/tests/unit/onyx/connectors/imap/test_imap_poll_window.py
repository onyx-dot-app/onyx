from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from onyx.connectors.imap.connector import _fetch_email_ids_in_mailbox


@pytest.mark.parametrize(
    "start,end,expected_since,expected_before,internal_dates,expected_ids",
    [
        pytest.param(
            "2026-10-09T10:00:00+00:00",
            "2026-10-09T10:05:00+00:00",
            "09-Oct-2026",
            "10-Oct-2026",
            ["2026-10-08T23:59:00+00:00", "2026-10-09T10:02:00+00:00"],
            ["2"],
            id="same-day-poll",
        ),
        pytest.param(
            "1970-01-01T00:00:00+00:00",
            "2026-10-09T10:05:00+00:00",
            "01-Jan-1970",
            "10-Oct-2026",
            ["2026-10-08T23:59:00+00:00", "2026-10-09T10:02:00+00:00"],
            ["1", "2"],
            id="initial-load-includes-today",
        ),
        pytest.param(
            "2026-10-08T23:30:00+00:00",
            "2026-10-09T00:05:00+00:00",
            "08-Oct-2026",
            "10-Oct-2026",
            ["2026-10-08T23:45:00+00:00", "2026-10-09T00:02:00+00:00"],
            ["1", "2"],
            id="cross-midnight-poll-offset",
        ),
        pytest.param(
            "2026-10-08T23:30:00+00:00",
            "2026-10-09T00:00:00+00:00",
            "08-Oct-2026",
            "09-Oct-2026",
            ["2026-10-08T23:45:00+00:00", "2026-10-09T00:00:00+00:00"],
            ["1"],
            id="exclusive-midnight-bound",
        ),
        pytest.param(
            "2026-12-31T23:00:00+00:00",
            "2026-12-31T23:59:59.999999+00:00",
            "31-Dec-2026",
            "01-Jan-2027",
            ["2026-12-31T23:30:00+00:00", "2027-01-01T00:00:00+00:00"],
            ["1"],
            id="year-rollover",
        ),
        pytest.param(
            "2024-02-29T10:00:00+00:00",
            "2024-02-29T10:05:00+00:00",
            "29-Feb-2024",
            "01-Mar-2024",
            ["2024-02-29T10:02:00+00:00"],
            ["1"],
            id="leap-day",
        ),
        pytest.param(
            "2026-10-09T07:50:00+08:00",
            "2026-10-09T08:05:00+08:00",
            "08-Oct-2026",
            "10-Oct-2026",
            ["2026-10-08T23:55:00+00:00", "2026-10-09T00:02:00+00:00"],
            ["1", "2"],
            id="timestamps-use-utc-days",
        ),
        pytest.param(
            "2026-10-09T10:00:00+00:00",
            "2026-10-09T10:05:00+00:00",
            "09-Oct-2026",
            "10-Oct-2026",
            ["2026-10-08T23:59:00+00:00", "2026-10-10T00:00:00+00:00"],
            [],
            id="empty-mailbox-range",
        ),
    ],
)
def test_imap_search_covers_poll_window_days(
    start: str,
    end: str,
    expected_since: str,
    expected_before: str,
    internal_dates: list[str],
    expected_ids: list[str],
) -> None:
    mail_client = MagicMock()
    mail_client.select.return_value = ("OK", [b""])

    def search(_charset: None, criteria: str) -> tuple[str, list[bytes]]:
        # IMAP compares INTERNALDATE's calendar date, not the sender's Date header.
        since = datetime.strptime(criteria.split('"')[1], "%d-%b-%Y").date()
        before = datetime.strptime(criteria.split('"')[3], "%d-%b-%Y").date()
        ids = [
            str(index)
            for index, internal_date in enumerate(internal_dates, start=1)
            if since <= datetime.fromisoformat(internal_date).date() < before
        ]
        return "OK", [" ".join(ids).encode()]

    mail_client.search.side_effect = search

    ids = _fetch_email_ids_in_mailbox(
        mail_client=mail_client,
        mailbox="INBOX",
        start=datetime.fromisoformat(start).astimezone(timezone.utc).timestamp(),
        end=datetime.fromisoformat(end).astimezone(timezone.utc).timestamp(),
    )

    assert ids == expected_ids
    mail_client.select.assert_called_once_with(mailbox="INBOX", readonly=True)
    mail_client.search.assert_called_once_with(
        None, f'(SINCE "{expected_since}" BEFORE "{expected_before}")'
    )
