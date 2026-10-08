# Log

**Import:** `import { Log } from "@opal/components";`

One line of a log or report: an icon, a title, details, and trailing content.
A list of checks, the steps of a job, or the entries of an audit trail are each
a column of `Log`s.

## Props

| Prop            | Type                            | Default     | Description                                                    |
| --------------- | ------------------------------- | ----------- | -------------------------------------------------------------- |
| `variant`       | `StatusVariants`                | `"default"` | Colours the icon and tints the row on hover                    |
| `icon`          | `IconFunctionComponent`         | —           | Shown at 1rem with 0.125rem padding                            |
| `title`         | `string \| RichStr`             | —           | `secondary-action`, one line, at most 10rem wide               |
| `details`       | `string \| RichStr`             | —           | `main-ui-body`, one line, fills the rest of the row            |
| `rightChildren` | `ReactNode`                     | —           | Trailing content, such as a tag or an action; not padded       |
| `interaction`   | `"rest" \| "hover" \| "active"` | —           | Overrides the interaction state; unset, it follows the pointer |

## Variants

| Variant   | Icon stroke                | Hover background     |
| --------- | ------------------- | -------------------- |
| `default` | `text-03`           | `background-tint-00` |
| `pending` | `text-03`           | `background-tint-00` |
| `info`    | `status-info-05`    | `status-info-00`     |
| `success` | `status-success-05` | `status-success-00`  |
| `warning` | `theme-amber-05`    | `theme-amber-01`     |
| `error`   | `status-error-05`   | `status-error-00`    |

The variant sets colours only; pass the icon that fits the state (for example
a spinner, a clock or an hourglass for `pending`).

## Layout

- `Interactive.Stateless` (`default`, `internal`) wraps an
  `Interactive.Container` of size `lg`: 2.25rem tall with 0.5rem padding, so
  tall trailing content cannot stretch the line.
- The contents sit in one row with a 0.25rem gap, centred.
- A title or details too long for its line is cut with an ellipsis and shows
  in full in a tooltip.

## Usage

```tsx
<Log
  variant="error"
  icon={SvgXCircle}
  title="Check attachment access"
  details="Attachment download timed out"
  rightChildren={<Tag title="Required" color="gray" />}
/>
```
