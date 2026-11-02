import datetime

import pytest

from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc


def test_time_str_to_utc() -> None:
    str_to_dt = {
        "Tue, 5 Oct 2021 09:38:25 GMT": datetime.datetime(
            2021, 10, 5, 9, 38, 25, tzinfo=datetime.timezone.utc
        ),
        "Sat, 24 Jul 2021 09:21:20 +0000 (UTC)": datetime.datetime(
            2021, 7, 24, 9, 21, 20, tzinfo=datetime.timezone.utc
        ),
        "Thu, 29 Jul 2021 04:20:37 -0400 (EDT)": datetime.datetime(
            2021, 7, 29, 8, 20, 37, tzinfo=datetime.timezone.utc
        ),
        "30 Jun 2023 18:45:01 +0300": datetime.datetime(
            2023, 6, 30, 15, 45, 1, tzinfo=datetime.timezone.utc
        ),
        "22 Mar 2020 20:12:18 +0000 (GMT)": datetime.datetime(
            2020, 3, 22, 20, 12, 18, tzinfo=datetime.timezone.utc
        ),
        "Date: Wed, 27 Aug 2025 11:40:00 +0200": datetime.datetime(
            2025, 8, 27, 9, 40, 0, tzinfo=datetime.timezone.utc
        ),
    }
    for strptime, expected_datetime in str_to_dt.items():
        assert time_str_to_utc(strptime) == expected_datetime


def test_time_str_to_utc_recovers_from_concatenated_headers() -> None:
    # TZ is dropped during recovery, so the expected result is UTC rather
    # than the original offset.
    assert time_str_to_utc(
        'Sat, 3 Nov 2007 14:33:28 -0200To: "jason" <jason@example.net>'
    ) == datetime.datetime(2007, 11, 3, 14, 33, 28, tzinfo=datetime.timezone.utc)

    assert time_str_to_utc(
        "Fri, 20 Feb 2015 10:30:00 +0500Cc: someone@example.com"
    ) == datetime.datetime(2015, 2, 20, 10, 30, 0, tzinfo=datetime.timezone.utc)


def test_time_str_to_utc_raises_on_impossible_dates() -> None:
    for bad in (
        "Wed, 33 Sep 2007 13:42:59 +0100",
        "Thu, 11 Oct 2007 31:50:55 +0900",
        "not a date at all",
        "",
    ):
        with pytest.raises(ValueError):
            time_str_to_utc(bad)
