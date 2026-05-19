---
name: slack
description: Read, search, and post Slack messages on the connected user's behalf via a light Slack Web API wrapper.
---

# Slack

The current user has connected their Slack account. Call Slack as that user
with the bundled helper. **You do not handle authentication** — requests to
`https://slack.com/api/*` are authenticated automatically by the Onyx egress
proxy. Never ask for or set a token.

## Usage

    python _external_apps/<this-dir>/slack_api.py <command> [args]

Read commands auto-paginate and prune empty fields. `post` is the only write.

    # List channels the user is in
    python slack_api.py channels

    # Recent messages in a channel (by channel ID)
    python slack_api.py history C0123456789 --limit 50

    # Replies in a thread
    python slack_api.py replies C0123456789 1700000000.000100

    # Workspace users / one user
    python slack_api.py users
    python slack_api.py user U0123456789

    # Search messages
    python slack_api.py search "deploy failed" --count 30

    # Post a message
    python slack_api.py post C0123456789 "Hello from Onyx"

    # Any other Slack method (raw escape hatch)
    python slack_api.py call chat.update '{"channel": "C0", "ts": "1.2", "text": "edited"}'

Use `--raw` on any command to skip empty-field pruning. `python slack_api.py
<command> -h` shows its flags.

## Output

JSON on stdout. Read commands return `{"ok": true, "<key>": [...], "count": N,
"truncated": bool}` (`truncated` means more results existed past `--limit`).
Failures pass Slack's response through verbatim: `{"ok": false, "error":
"<code>"}` (e.g. `not_in_channel`, `missing_scope`) and exit non-zero — surface
`error` rather than retrying blindly.

## Notes

- Channels/users are referenced by ID (e.g. `C…`, `U…`); resolve names via
  `channels` / `users` first.
- Scopes were chosen by the admin. You cannot widen them; on `missing_scope`
  tell the user which scope is needed.
- Never print or ask for the access token; you do not have it and do not need
  it.
