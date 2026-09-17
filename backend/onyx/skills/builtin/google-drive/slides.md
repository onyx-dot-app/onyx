# Google Slides (`gslides_api.py`)

Read and **edit presentations** via `https://slides.googleapis.com/v1/`.
`gdrive_api.py read` (see [drive.md](drive.md)) still exports a deck as plain
text; the commands here expose slide/element `objectId`s, which edits target.
`<presentation_id>` is the Drive file id of the deck.

    python .opencode/skills/google-drive/gslides_api.py <command> [args]

## Read a deck

```
python gslides_api.py get <presentation_id> [--fields ...]
python gslides_api.py text <presentation_id>
python gslides_api.py page <presentation_id> <page_object_id>
```

`get` returns a compact structure view (slides, element `objectId`s, shape text);
`text` returns just the plain text per slide; `page` returns one slide in full.

## Create and grow a deck (write)

```
python gslides_api.py create --title "Roadmap"
python gslides_api.py add-slide <presentation_id> [--layout TITLE_AND_BODY]
```

`add-slide` appends a slide with a predefined layout (`BLANK`, `TITLE`,
`TITLE_AND_BODY`, `SECTION_HEADER`, ...) and returns the new slide's `objectId`.

## Edit text (write)

```
python gslides_api.py insert-text <presentation_id> <shape_object_id> --text "..."
python gslides_api.py replace-text <presentation_id> --find "{{name}}" --replace "Ada"
```

`insert-text` needs a shape `objectId` from `get`. `replace-text` swaps every
occurrence across the deck — the reliable way to fill placeholder text.

## Raw batchUpdate (write)

```
python gslides_api.py batch-update <presentation_id> '[<request>, ...]'
python gslides_api.py batch-update <presentation_id> --file requests.json
```

The escape hatch for everything else — a JSON **array** of Slides API request
objects (e.g. `createShape`, `createTable`, `updateTextStyle`, `deleteObject`,
`updatePageElementTransform`).

## Output

`create` returns `{"ok": true, "presentation": {...}}`; `get` and `page` return
the same under `"presentation"` / `"page"`. `text` returns `{"ok": true,
"title", "slides": [{"index", "objectId", "text"}]}`. `add-slide` returns
`{"ok": true, "objectId": ..., "data": {...}}`; other writes return `{"ok":
true, "data": {...}}`.
