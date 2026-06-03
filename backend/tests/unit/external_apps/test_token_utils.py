from datetime import datetime
from datetime import timedelta
from datetime import timezone

from onyx.external_apps.token_utils import needs_refresh
from onyx.external_apps.token_utils import stamp_expires_at

_NOW = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# stamp_expires_at
# ---------------------------------------------------------------------------


def test_stamp_expires_at_computes_absolute_instant() -> None:
    stamped = stamp_expires_at({"access_token": "a", "expires_in": 3600}, _NOW)
    assert stamped["expires_at"] == (_NOW + timedelta(seconds=3600)).isoformat()
    # original fields preserved
    assert stamped["access_token"] == "a"


def test_stamp_expires_at_no_expires_in_is_passthrough() -> None:
    creds = {"access_token": "a"}
    stamped = stamp_expires_at(creds, _NOW)
    assert "expires_at" not in stamped


def test_stamp_expires_at_does_not_mutate_input() -> None:
    creds = {"access_token": "a", "expires_in": 60}
    stamp_expires_at(creds, _NOW)
    assert "expires_at" not in creds  # built a new dict


def test_stamp_expires_at_bad_expires_in_stamps_already_expired() -> None:
    # A corrupt expiry must not read as a non-expiring token: stamp it as
    # already-expired so the refresh path heals it on next use.
    stamped = stamp_expires_at({"access_token": "a", "expires_in": "soon"}, _NOW)
    assert stamped["expires_at"] == _NOW.isoformat()
    assert needs_refresh(stamped, _NOW) is True


# ---------------------------------------------------------------------------
# needs_refresh
# ---------------------------------------------------------------------------


def test_needs_refresh_fresh_token_is_false() -> None:
    expires_at = (_NOW + timedelta(hours=1)).isoformat()
    assert needs_refresh({"expires_at": expires_at}, _NOW) is False


def test_needs_refresh_expired_token_is_true() -> None:
    expires_at = (_NOW - timedelta(minutes=5)).isoformat()
    assert needs_refresh({"expires_at": expires_at}, _NOW) is True


def test_needs_refresh_within_skew_is_true() -> None:
    # 60s left, default skew is 120s → refresh early.
    expires_at = (_NOW + timedelta(seconds=60)).isoformat()
    assert needs_refresh({"expires_at": expires_at}, _NOW) is True


def test_needs_refresh_missing_expires_at_is_false() -> None:
    # Slack / Linear / static-credential apps never expire (key absent).
    assert needs_refresh({"access_token": "a"}, _NOW) is False


def test_needs_refresh_present_but_falsy_expires_at_is_true() -> None:
    # A present-but-empty/null value is corrupt, NOT a non-expiring token: it must
    # be distinguished from the missing key and routed to refresh, not treated as
    # never-expiring (which would leave an invalid token un-refreshed forever).
    assert needs_refresh({"expires_at": ""}, _NOW) is True
    assert needs_refresh({"expires_at": None}, _NOW) is True


def test_needs_refresh_unparseable_expires_at_is_true() -> None:
    # A present-but-corrupt expiry isn't a non-expiring token: refresh (heal it)
    # rather than silently keep a token of unknown validity in use.
    assert needs_refresh({"expires_at": "not-a-date"}, _NOW) is True


def test_needs_refresh_non_string_expires_at_is_true() -> None:
    # A truthy non-string value also fails parsing → treat as needing refresh.
    assert needs_refresh({"expires_at": 1234567890}, _NOW) is True


def test_needs_refresh_naive_expires_at_treated_as_utc() -> None:
    naive = (_NOW.replace(tzinfo=None) - timedelta(minutes=1)).isoformat()
    assert needs_refresh({"expires_at": naive}, _NOW) is True
