---
name: google-calendar
description: Read and manage the connected user's Google Calendar via a light Calendar API wrapper.
---

# Google Calendar

The current user has connected their Google Calendar. Call it as that user
with the bundled helper. **You do not handle authentication** — requests to
`https://www.googleapis.com/calendar/*` are authenticated automatically by the
Onyx egress proxy. Never ask for or set a token.

## Usage

    python _external_apps/<this-dir>/gcal_api.py <command> [args]

Read commands auto-paginate and prune empty fields. `create-event` and
`delete-event` are the only writes. `primary` is the user's default calendar.

    # The user's calendars
    python gcal_api.py calendars

    # Events in a window (RFC3339 timestamps)
    python gcal_api.py events primary --from 2026-06-01T00:00:00Z --to 2026-06-08T00:00:00Z
    python gcal_api.py events primary --q "standup" --limit 50

    # One event
    python gcal_api.py event primary <event_id>

    # Create / delete an event (writes)
    python gcal_api.py create-event primary "Sync" 2026-06-01T10:00:00Z 2026-06-01T10:30:00Z \
        --description "Weekly" --attendees a@x.com,b@x.com
    python gcal_api.py delete-event primary <event_id>

    # Free/busy across calendars
    python gcal_api.py freebusy 2026-06-01T00:00:00Z 2026-06-02T00:00:00Z primary

    # Any other Calendar endpoint (raw escape hatch)
    python gcal_api.py call PATCH calendars/primary/events/<id> '{"summary":"Renamed"}'

Use `--raw` to skip empty-field pruning. `python gcal_api.py <command> -h`
shows its flags.

## Output

JSON on stdout. List commands return `{"ok": true, "items": [...], "count": N,
"truncated": bool}` (`truncated` means more existed past `--limit`). Transport
errors print to stderr and exit non-zero — Google's error JSON (with `code` and
`message`) is included; surface it rather than retrying blindly.

## Notes

- Times are RFC3339 (e.g. `2026-06-01T10:00:00Z`); `events` returns expanded
  single instances ordered by start time.
- Never print or ask for the access token; you do not have it and do not need
  it.
