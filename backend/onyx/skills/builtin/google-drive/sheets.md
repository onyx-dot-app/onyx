# Google Sheets (`gsheets_api.py`)

Read and **surgically edit spreadsheets** via
`https://sheets.googleapis.com/v4/`. `gdrive_api.py read` (see
[drive.md](drive.md)) still exports a Sheet as CSV; the commands here read
structure, target A1 ranges, and write cells. `<spreadsheet_id>` is the Drive
file id of the Sheet.

    python .opencode/skills/google-drive/gsheets_api.py <command> [args]

## Read structure and values

```
python gsheets_api.py get <spreadsheet_id> [--fields ...]
python gsheets_api.py values <spreadsheet_id> "Sheet1!A1:C10" [--formulas]
```

`get` lists the sheets (tabs) with their `sheetId` and grid size. `values` takes
A1 notation; a bare sheet title reads the whole tab.

## Create a spreadsheet (write)

```
python gsheets_api.py create --title "Budget" [--sheet "Q1" --sheet "Q2"]
```

To build a Sheet from a produced CSV instead, use `gdrive_api.py upload
--convert-to application/vnd.google-apps.spreadsheet`.

## Write cell values (write)

```
python gsheets_api.py update-values <spreadsheet_id> "Sheet1!A1" '[["a","b"],[1,2]]'
python gsheets_api.py append-values <spreadsheet_id> "Sheet1" '[["new","row"]]'
python gsheets_api.py clear-values <spreadsheet_id> "Sheet1!A2:B10"
```

Values are a JSON array of row arrays (`--file values.json` instead of inline).
Input is parsed like UI entry (numbers, dates, `=SUM(A1:A5)` formulas); pass
`--raw-input` to store strings verbatim. `append-values` adds rows after the
last row of the table that contains the given range.

## Structural edits: raw batchUpdate (write)

```
python gsheets_api.py batch-update <spreadsheet_id> '[<request>, ...]'
python gsheets_api.py batch-update <spreadsheet_id> --file requests.json
```

The escape hatch for everything else — a JSON **array** of Sheets API request
objects (e.g. `addSheet`, `deleteSheet`, `repeatCell`, `mergeCells`,
`updateBorders`, `autoResizeDimensions`). Requests that target a tab need its
numeric `sheetId` from `get` (not the tab title).

## Output

`get` / `create` return `{"ok": true, "spreadsheet": {...}}`. `values` and the
write commands return `{"ok": true, "data": {...}}`.
