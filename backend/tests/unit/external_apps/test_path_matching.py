"""Unit tests for RestRoute path-template matching."""

import pytest

from onyx.external_apps.providers.actions import path_matches


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
    ],
)
def test_path_matches(template: str, path: str, expected: bool) -> None:
    assert path_matches(template, path) is expected
