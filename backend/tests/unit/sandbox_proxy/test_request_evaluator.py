"""Unit tests for the proxy's URL → ExternalApp resolution.

``resolve_app_for_url`` binds a request to a connected app before deferring to
``external_apps.matching.recognize_actions``. Transient (un-flushed)
``ExternalApp`` objects suffice — it only reads ``upstream_url_patterns``, never
the DB. CUSTOM apps author globs; built-in providers author regexes.
"""

from __future__ import annotations

from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.sandbox_proxy.request_evaluator import resolve_app_for_url


def _app(
    patterns: list[str],
    app_type: ExternalAppType = ExternalAppType.CUSTOM,
) -> ExternalApp:
    return ExternalApp(app_type=app_type, upstream_url_patterns=patterns)


def test_custom_glob_matches_deep_path() -> None:
    # `/api/*` must cover deep paths (the Discord 401 regression).
    app = _app(["https://discord.com/api/*"])
    assert resolve_app_for_url("https://discord.com/api/v10/users/@me", [app]) is app
    # The dot is literal, so a look-alike host must not match.
    assert resolve_app_for_url("https://discordxcom/api/x", [app]) is None


def test_builtin_regex_used_as_is() -> None:
    slack = _app(["https://slack\\.com/api/.*"], ExternalAppType.SLACK)
    assert (
        resolve_app_for_url("https://slack.com/api/chat.postMessage", [slack]) is slack
    )


def test_no_pattern_matches_returns_none() -> None:
    app = _app(["https://slack.com/api/*"])
    assert resolve_app_for_url("https://example.com/", [app]) is None


def test_empty_patterns_never_match() -> None:
    assert resolve_app_for_url("https://slack.com/api/x", [_app([])]) is None


def test_first_app_in_order_wins_on_overlap() -> None:
    broad = _app(["https://slack.com/*"])
    narrow = _app(["https://slack.com/api/*"])
    # Caller passes apps id-ordered; the earlier one wins.
    assert resolve_app_for_url("https://slack.com/api/x", [broad, narrow]) is broad


def test_malformed_builtin_regex_is_skipped_not_fatal() -> None:
    bad = _app(["("], ExternalAppType.SLACK)  # invalid regex
    good = _app(["https://slack\\.com/api/.*"], ExternalAppType.SLACK)
    assert resolve_app_for_url("https://slack.com/api/x", [bad, good]) is good
