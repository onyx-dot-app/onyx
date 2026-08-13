# Google Docs (`gdrive_api.py` Docs commands)

Surgically edit or create a Google Doc (insert/delete text, restyle paragraphs,
add bullets) via `https://docs.googleapis.com/v1/` — a different host than
Drive. `gdrive_api.py read` gives you a Doc's text, but Docs edits need
character **indices**, so fetch the structure first with `get-doc`. Note:
`<document_id>` is the Drive file id of the Doc.

    python .opencode/skills/google-drive/gdrive_api.py <command> [args]

## Get a Doc's structure (indices)

```
python gdrive_api.py get-doc <document_id> [--fields "documentId,body,title"]
```

Returns the document's `body.content` with each element's `startIndex` /
`endIndex`. Use these indices to target edits precisely.

## Insert text at an index (write)

```
python gdrive_api.py insert-text <document_id> --index N --text "..."
```

Issues a `batchUpdate` with a single `insertText` request at character index `N`
(get the index from `get-doc`).

## Append text to the end of a Doc (write)

```
python gdrive_api.py append-text <document_id> --text "..."
```

Fetches the Doc, computes the end of the body, and inserts the text there — no
manual index needed.

## Apply raw batchUpdate requests (write)

```
python gdrive_api.py batch-update <document_id> '[<request>, ...]'
python gdrive_api.py batch-update <document_id> --file requests.json
```

The general escape hatch: pass a JSON **array** of Docs API request objects, sent
as `{"requests": [...]}` to `documents/<id>:batchUpdate`. Supports the full Docs
request set, e.g. `insertText`, `deleteContentRange`, `updateParagraphStyle`,
`createParagraphBullets`, `updateTextStyle`. Example — bold a range then bullet a
paragraph:

```
python gdrive_api.py batch-update <document_id> '[
  {"updateTextStyle": {"range": {"startIndex": 1, "endIndex": 10},
    "textStyle": {"bold": true}, "fields": "bold"}},
  {"createParagraphBullets": {"range": {"startIndex": 1, "endIndex": 10},
    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE"}}
]'
```

## Create a new Google Doc (write)

```
python gdrive_api.py create-doc --title "My Doc"
```

Creates a new empty Doc via the Docs API and returns its `documentId` (then use
`insert-text` / `batch-update` to fill it). To create a Doc from existing
markdown/HTML content instead, use `upload --convert-to
application/vnd.google-apps.document` (see [drive.md](drive.md)).

## Output

`get-doc` / `create-doc` return `{"ok": true, "document": {...}}`.
`insert-text` / `append-text` / `batch-update` return `{"ok": true, "data":
{...}}` (`append-text` also echoes the computed `index`).
