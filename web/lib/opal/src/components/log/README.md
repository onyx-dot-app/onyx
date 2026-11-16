# Log

**Import:** `import { Log } from "@opal/components";`

One line of a log or report: a title column and centre content. A list of
checks, the steps of a job, or the entries of an audit trail are each a column
of `Log`s, and the columns line up from line to line. It shares its row with
[`Line`](../cards/line/README.md) (from the internal
[`line-base`](../cards/line-base/README.md)).

## Props

`variant`, `padding`, `icon`, `rightChildren`, `expandable`, `expanded` and
`expandedContent`, as on [`Line`](../cards/line/README.md), plus:

| Prop             | Type                | Default | Description                                                                  |
| ---------------- | ------------------- | ------- | ---------------------------------------------------------------------------- |
| `title`          | `string \| RichStr` | —       | `secondary-action` in `text-03`, one line, in a 10rem column                 |
| `centerChildren` | `ReactNode`         | —       | Fills the rest of the row from its start; the caller sets its colour and fit |
| `onClick`        | `() => void`        | —       | Makes the whole log, line and body, one interactive surface                  |

Trailing content (a tag, actions, a fold chevron) goes in `rightChildren`.

## Layout

The title column is exactly 10rem, and 1rem separates it from the centre
content. A title too long for its column is cut with an ellipsis and shows in
full in a tooltip. `centerChildren` handles its own overflow.

Unlike `Line`, a `Log` with `onClick` hovers and presses as one surface with
its body, and a click anywhere on it but a link calls `onClick`.

## Usage

```tsx
<Log
  variant="error-heavy"
  icon={SvgXCircle}
  title="Check attachment access"
  centerChildren={
    <Text font="main-ui-body" color="status-error-05" maxLines={1}>
      Attachment download timed out
    </Text>
  }
  rightChildren={<Tag title="Required" color="gray" />}
/>
```
