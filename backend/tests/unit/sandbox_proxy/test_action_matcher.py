"""Unit tests for the proxy's URL → ExternalApp resolution.

``resolve_app_for_url`` is the proxy-side glue that binds a request to a
connected app before deferring to ``external_apps.matching.match_action``.
Transient (un-flushed) ``ExternalApp`` objects suffice — it only reads
``upstream_url_patterns`` (and ``id`` for a warning log), never the DB.
"""

from __future__ import annotations

from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.sandbox_proxy.action_matcher import resolve_app_for_url


def _app(
    patterns: list[str],
    app_type: ExternalAppType = ExternalAppType.CUSTOM,
) -> ExternalApp:
    return ExternalApp(app_type=app_type, upstream_url_patterns=patterns)


def test_matches_the_app_whose_pattern_fires() -> None:
    slack = _app(["https://slack\\.com/api/.*"], ExternalAppType.SLACK)
    gcal = _app(
        ["https://www\\.googleapis\\.com/calendar/.*"],
        ExternalAppType.GOOGLE_CALENDAR,
    )
    apps = [slack, gcal]

    assert resolve_app_for_url("https://slack.com/api/chat.postMessage", apps) is slack
    assert resolve_app_for_url("https://www.googleapis.com/calendar/v3/x", apps) is gcal


def test_no_pattern_matches_returns_none() -> None:
    slack = _app(["https://slack\\.com/api/.*"])
    assert resolve_app_for_url("https://example.com/", [slack]) is None


def test_empty_patterns_never_match() -> None:
    assert resolve_app_for_url("https://slack.com/api/x", [_app([])]) is None


def test_first_app_in_order_wins_on_overlap() -> None:
    broad = _app(["https://slack\\.com/.*"])
    narrow = _app(["https://slack\\.com/api/.*"])
    # Caller passes apps id-ordered; the earlier one wins.
    assert resolve_app_for_url("https://slack.com/api/x", [broad, narrow]) is broad


def test_malformed_pattern_is_skipped_not_fatal() -> None:
    bad = _app(["("])  # invalid regex
    good = _app(["https://slack\\.com/api/.*"])
    # The bad pattern is skipped; resolution continues to the good app.
    assert resolve_app_for_url("https://slack.com/api/x", [bad, good]) is good
