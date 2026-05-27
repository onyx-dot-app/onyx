---
name: google-calendar
description: Read and manage the connected user's Google Calendar via a light Calendar API wrapper.
---

# Google Calendar

Call the Google Calendar API as the connected user via the bundled helper.

## Usage

    python .opencode/skills/google-calendar/gcal_api.py <command> [args]

Read commands auto-paginate and prune empty fields. `create-event` and
`delete-event` are the only writes. `primary` is the user's default calendar.
Use `--raw` to skip empty-field pruning; `python gcal_api.py <command> -h`
shows its flags.

### List calendars

```
python gcal_api.py calendars [--limit N]
```

### List events

```
python gcal_api.py events primary [--from ISO] [--to ISO] [--q TEXT] [--limit N]
```

### One event

```
python gcal_api.py event primary <event_id>
```

### Create an event (write)

```
python gcal_api.py create-event primary "Sync" 2026-06-01T10:00:00Z 2026-06-01T10:30:00Z \
    [--description D] [--attendees a@x.com,b@x.com]
```

### Delete an event (destructive)

```
python gcal_api.py delete-event primary <event_id>
```

### Free/busy

```
python gcal_api.py freebusy 2026-06-01T00:00:00Z 2026-06-02T00:00:00Z primary
```

## Output

JSON on stdout. List commands return `{"ok": true, "items": [...], "count": N,
"truncated": bool}` (`truncated` means more results existed past `--limit`).
Transport errors print to stderr and exit non-zero; Google's error JSON (with
`code` and `message`) is included.

## Notes

- Times are RFC3339 (e.g. `2026-06-01T10:00:00Z`); `events` returns expanded
  single instances ordered by start time.