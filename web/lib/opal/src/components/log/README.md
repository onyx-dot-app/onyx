# Log

**Import:** `import { Log } from "@opal/components";`

One line of a log or report: an icon, a title, details, and trailing content.
A list of checks, the steps of a job, or the entries of an audit trail are each
a column of `Log`s. A line is not interactive.

## Props

| Prop            | Type                    | Default     | Description                                                               |
| --------------- | ----------------------- | ----------- | ------------------------------------------------------------------------- |
| `variant`       | `LogVariant`            | `"default"` | Status and weight: colours the icon; heavy also colours details and tints |
| `icon`          | `IconFunctionComponent` | —           | Shown at 1rem with 0.125rem padding                                       |
| `title`         | `string \| RichStr`     | —           | `secondary-action` in `text-03`, one line, at most 10rem wide             |
| `details`       | `string \| RichStr`     | —           | `main-ui-body`, start-aligned, one line, fills the row                    |
| `rightChildren` | `ReactNode`             | —           | Trailing content, such as a tag or an action; not padded                  |

## Variants

`LogVariant` is `"default"` or a status and a weight, e.g. `"error-heavy"`. The
statuses are a subset of `StatusVariants`:
`LogStatus = Extract<StatusVariants, "default" | "success" | "warning" | "error">`.

| Status    | Icon                | `heavy` details     | `heavy` background  |
| --------- | ------------------- | ------------------- | ------------------- |
| `default` | `text-03`           | — (never heavy)     | —                   |
| `success` | `status-success-05` | `status-success-05` | `status-success-01` |
| `warning` | `theme-amber-05`    | `theme-amber-05`    | `theme-amber-01`    |
| `error`   | `status-error-05`   | `status-error-05`   | `status-error-01`   |

A `light` line has no background, and its details stay `text-04`: only the
icon carries the status. `default` details are `text-03`. Use `heavy` for the lines that need action,
such as a failure that blocks. The variant sets colours only; pass the icon
that fits the state (for example a spinner, a clock or an hourglass).

## Layout

- A row `Section`, 2.25rem tall with 0.5rem padding and a 0.25rem gap, so tall
  trailing content cannot stretch the line.
- A title or details too long for its line is cut with an ellipsis and shows
  in full in a tooltip.

## Usage

```tsx
<Log
  variant="error-heavy"
  icon={SvgXCircle}
  title="Check attachment access"
  details="Attachment download timed out"
  rightChildren={<Tag title="Required" color="gray" />}
/>
```
