# CodePanel

**Import:** `import { CodePanel } from "@opal/components";`

A bordered panel for code, such as a command and its output, a file, or a
diff. It is composable: put the parts you need inside `CodePanel`, top to
bottom. Each part after the first draws a divider above itself. Code is
always left to right.

| Part                 | Use                                                                                         |
| -------------------- | ------------------------------------------------------------------------------------------- |
| `CodePanel.Header`   | Optional title row: a mono title (`background-tint-01`), controls, and a copy button        |
| `CodePanel.Lines`    | The code, one row per line: optional line numbers and diff markers; scrolls past 24rem      |
| `CodePanel.Columns`  | Two `Lines` side by side that scroll together, e.g. a split diff                            |
| `CodePanel.Output`   | Optional output text (`background-tint-00`), or `error` output (red on a red tint)          |
| `CodePanel.Footer`   | Optional closing row, e.g. "12 more lines" and a "Show all" button                          |

Highlighting is the caller's: pass each line's `content` as plain text or as
highlighted markup.

## Props

### `CodePanel.Header`

| Prop            | Type                | Default | Description                                                  |
| --------------- | ------------------- | ------- | ------------------------------------------------------------ |
| `title`         | `string \| RichStr` | —       | E.g. a file path or a language. One line, with a tooltip when cut |
| `rightChildren` | `ReactNode`         | —       | Controls before the copy button, e.g. stats or a view toggle |
| `copyText`      | `string`            | —       | Adds a copy button at the end of the row                     |

### `CodePanel.Lines`

| Prop          | Type              | Default | Description                                                                 |
| ------------- | ----------------- | ------- | --------------------------------------------------------------------------- |
| `lines`       | `CodePanelLine[]` | —       | `{ content, number?, kind? }`                                               |
| `lineNumbers` | `boolean`         | `false` | Shows each line's `number` in a gutter (`background-tint-01`)               |
| `markers`     | `boolean`         | `false` | Shows a `+` / `-` column for diff lines                                     |
| `copyText`    | `string`          | —       | A copy button that appears on hover at the top end, for a panel without a header |

`kind` is `"context"` (default), `"added"` (green tint, `+`), `"removed"`
(red tint, `-`) or `"note"` (a full-width italic line, e.g. "12 unchanged
lines").

### `CodePanel.Output`

| Prop       | Type      | Default | Description                  |
| ---------- | --------- | ------- | ---------------------------- |
| `children` | `string`  | —       | The output text              |
| `error`    | `boolean` | `false` | Red text on a red tint       |

### `CodePanel.Footer`

| Prop            | Type                | Default | Description                     |
| --------------- | ------------------- | ------- | ------------------------------- |
| `title`         | `string \| RichStr` | —       | E.g. "12 more lines"            |
| `rightChildren` | `ReactNode`         | —       | Controls, e.g. "Show all"       |

## Usage

```tsx
// A command and its output
<CodePanel>
  <CodePanel.Header title="python" copyText={code} />
  <CodePanel.Lines lineNumbers lines={code.split("\n").map((content, i) => ({ content, number: i + 1 }))} />
  <CodePanel.Output>{stdout}</CodePanel.Output>
  <CodePanel.Output error>{stderr}</CodePanel.Output>
</CodePanel>

// A diff
<CodePanel>
  <CodePanel.Header title="app/page.tsx" rightChildren={stats} copyText={newText} />
  <CodePanel.Lines lineNumbers markers lines={diffLines} />
</CodePanel>
```
