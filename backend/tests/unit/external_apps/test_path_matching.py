"""Unit tests for RestRoute path-template matching."""

import pytest
from pydantic import ValidationError

from onyx.external_apps.providers.actions import path_matches
from onyx.external_apps.providers.actions import RestRoute


def test_non_trailing_wildcard_rejected_at_construction() -> None:
    """A `{name...}` wildcard is only valid as the last segment; defining it
    elsewhere must fail loudly when the catalog loads, not mis-match silently."""
    with pytest.raises(ValidationError, match="must be the last segment"):
        RestRoute(method="GET", path="/repos/{owner...}/issues")
    # Trailing position stays valid.
    RestRoute(method="GET", path="/repos/{owner}/{repo}/contents/{path...}")


@pytest.mark.parametrize(
    "template, path, expected",
    [
        # Literal paths (Slack-style).
        ("/api/conversations.list", "/api/conversations.list", True),
        ("/api/conversations.list", "/api/conversations.history", False),
        # Placeholder matches exactly one segment.
        (
            "/calendar/v3/calendars/{calendarId}/events",
            "/calendar/v3/calendars/primary/events",
            True,
        ),
        (
            "/calendar/v3/users/{userId}/calendarList",
            "/calendar/v3/users/me@example.com/calendarList",
            True,
        ),
        # Collection vs item must not cross-match (segment counts differ).
        (
            "/calendar/v3/calendars/{calendarId}/events",
            "/calendar/v3/calendars/primary/events/evt123",
            False,
        ),
        (
            "/calendar/v3/calendars/{calendarId}/events/{eventId}",
            "/calendar/v3/calendars/primary/events/evt123",
            True,
        ),
        # A placeholder does not span '/'.
        (
            "/calendar/v3/calendars/{calendarId}/events",
            "/calendar/v3/calendars/a/b/events",
            False,
        ),
        # A single trailing slash is ignored on either side.
        ("/calendar/v3/freeBusy", "/calendar/v3/freeBusy/", True),
        (
            "/calendar/v3/calendars/{calendarId}/events/",
            "/calendar/v3/calendars/primary/events",
            True,
        ),
        # A placeholder requires a non-empty segment.
        (
            "/calendar/v3/calendars/{calendarId}/events",
            "/calendar/v3/calendars//events",
            False,
        ),
        # Trailing {name...} wildcard matches one or more remaining segments
        # (a file path under contents, a slash-bearing ref).
        ("/repos/{o}/{r}/contents/{path...}", "/repos/o/r/contents/README.md", True),
        (
            "/repos/{o}/{r}/contents/{path...}",
            "/repos/o/r/contents/backend/onyx/main.py",
            True,
        ),
        ("/repos/{o}/{r}/git/ref/{ref...}", "/repos/o/r/git/ref/heads/feature/x", True),
        ("/repos/{o}/{r}/git/ref/{ref...}", "/repos/o/r/git/ref/heads", True),
        # The wildcard needs at least one trailing segment.
        ("/repos/{o}/{r}/contents/{path...}", "/repos/o/r/contents", False),
        # An empty tail segment (`//`) must be rejected, like single placeholders.
        ("/repos/{o}/{r}/contents/{path...}", "/repos/o/r/contents//evil", False),
        ("/repos/{o}/{r}/contents/{path...}", "/repos/o/r/contents/a//b", False),
        # The fixed prefix before the wildcard must still match exactly.
        ("/repos/{o}/{r}/contents/{path...}", "/repos/o/r/blobs/a.py", False),
        # A trailing slash after the wildcard tail is ignored.
        ("/repos/{o}/{r}/contents/{path...}", "/repos/o/r/contents/a/b/", True),
    ],
)
def test_path_matches(template: str, path: str, expected: bool) -> None:
    assert path_matches(template, path) is expected
