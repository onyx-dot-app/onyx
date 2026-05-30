---
name: gmail
description: Read, search, and send email from the connected user's Gmail via a light Gmail API wrapper.
---

# Gmail

Call the Gmail API as the connected user via the bundled helper.

## Usage

    python .opencode/skills/gmail/gmail_api.py <command> [args]

Read commands auto-paginate and prune empty fields. `send`, `modify`, and
`trash` are the only writes; there is no permanent delete. `me` is always the
connected user. Use `--raw` to skip empty-field pruning; `python gmail_api.py
<command> -h` shows its flags.

### List / search messages

Lists message headers (From, Subject, Date, snippet). `--q` takes Gmail search
syntax (e.g. `is:unread from:boss@x.com newer_than:7d`).

```
python gmail_api.py messages [--q QUERY] [--label LABEL_ID] [--limit N]
```

### One message

Full message with decoded plain-text body.

```
python gmail_api.py message <message_id>
```

### Send a message (write)

```
python gmail_api.py send to@x.com "Subject" "Body text" \
    [--cc a@x.com,b@x.com] [--bcc c@x.com]
```

### List labels

```
python gmail_api.py labels
```

### Modify labels on a message (write)

Add or remove label IDs. Mark read by removing `UNREAD`; archive by removing
`INBOX`.

```
python gmail_api.py modify <message_id> [--add LABEL,LABEL] [--remove LABEL,LABEL]
```

### Trash a message (write, reversible)

```
python gmail_api.py trash <message_id>
```

### Profile

```
python gmail_api.py profile
```

## Output

JSON on stdout. List commands return `{"ok": true, "items": [...], "count": N,
"truncated": bool}` (`truncated` means more results existed past `--limit`).
Transport errors print to stderr and exit non-zero; Google's error JSON (with
`code` and `message`) is included.

## Notes

- Message bodies are returned decoded from base64url; for multipart messages the
  first `text/plain` part is used.
- Common system label IDs: `INBOX`, `UNREAD`, `STARRED`, `SENT`, `TRASH`,
  `SPAM`, `IMPORTANT`.
