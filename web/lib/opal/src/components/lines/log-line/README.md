# LogLine

**Import:** `import { LogLine } from "@opal/components";`

One line of a log or report: a title column and centre content. A list of
checks, the steps of a job, or the entries of an audit trail are each a column
of `LogLine`s, and the columns line up from line to line. It shares its frame
with [`Line`](../line/README.md) (from the internal
[`line-base`](../line-base/README.md)).

## Props

| Prop              | Type                    | Default     | Description                                                                                                     |
| ----------------- | ----------------------- | ----------- | --------------------------------------------------------------------------------------------------------------- |
| `variant`         | `LineVariant`           | `"default"` | Status and weight: colours the icon; heavy also tints the line and its body                                     |
| `padding`         | `0 \| 1`                | `1`         | The outer padding, as a spacing step (`N / 4` rem). `0` for a line inside a container that pads it already      |
| `icon`            | `IconFunctionComponent` | —           | Shown at 1rem with 0.125rem padding                                                                             |
| `title`           | `string \| RichStr`     | —           | `secondary-action` in `text-03`, one line, in a 10rem column                                                    |
| `centerChildren`  | `ReactNode`             | —           | Fills the rest of the row from its start; the caller sets its colour and fit                                    |
| `rightChildren`   | `ReactNode`             | —           | Trailing content at the very end (a tag, actions, a fold chevron), outside the line's inner padding; not padded |
| `onClick`         | `() => void`            | —           | Makes the whole log, line and body, one interactive surface                                                     |
| `expandable`      | `true`                  | —           | Enables `expanded` and `expandedContent`                                                                        |
| `expanded`        | `boolean`               | —           | Whether the body is open; controlled, the caller owns the state                                                 |
| `expandedContent` | `ReactNode`             | —           | The body, opened in a `Fold` and aligned under the content                                                      |

Trailing content (a tag, actions, a fold chevron) goes in `rightChildren`.

## Variants

`LineVariant` is `"default"` or a status and a weight, e.g. `"error-heavy"`. The
statuses are a subset of `StatusColor`:
`LineStatus = Extract<StatusColor, "default" | "info" | "success" | "warning" | "error">`.

| Status    | Icon                | `heavy` background  |
| --------- | ------------------- | ------------------- |
| `default` | `text-03`           | — (never heavy)     |
| `info`    | `status-info-05`    | `status-info-00`    |
| `success` | `status-success-05` | `status-success-00` |
| `warning` | `status-warning-05` | `status-warning-00` |
| `error`   | `status-error-05`   | `status-error-00`   |

A `light` line has no background. The variant sets colours only; pass the icon
that fits the state (for example a spinner or an alert).

## Layout

The title column is exactly 10rem, and 1rem separates it from the centre
content. A title too long for its column is cut with an ellipsis and shows in
full in a tooltip. `centerChildren` handles its own overflow.

With `onClick`, the row and the body hover and press as one surface, and a
click on the row (not on a link) calls `onClick`. The body keeps its text
selection, its cursor and its own clicks, so selecting or clicking in it never
toggles the line.

## Usage

```tsx
<LogLine
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
