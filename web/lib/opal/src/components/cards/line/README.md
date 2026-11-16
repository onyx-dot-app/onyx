# Line

**Import:** `import { Line } from "@opal/components";`

One line of a list or a timeline: an icon, a title and trailing content. A
line is plain unless it gets `onClick`, and it can open a body below it with
`expandable`. Like an expandable [`SelectCard`](../select-card/README.md), only
the row is interactive: clicks and text selection in the body never reach
`onClick`. [`Log`](../../log/README.md) shares the same row (from the internal
[`line-base`](../line-base/README.md)) with a log's column layout, and makes
its body interactive too.

## Props

| Prop              | Type                    | Default     | Description                                                                                                         |
| ----------------- | ----------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------- |
| `variant`         | `LineVariant`           | `"default"` | Status and weight: colours the icon; heavy also tints the line and its body                                         |
| `padding`         | `0 \| 1`                | `1`         | The outer padding, as a spacing step (`N / 4` rem). `0` for a line inside a container that pads it already          |
| `icon`            | `IconFunctionComponent` | —           | Shown at 1rem with 0.125rem padding                                                                                 |
| `title`           | `string \| RichStr`     | —           | `secondary-action` in `text-03`. Fills the row, on one line, cut with an ellipsis and shown in full in a tooltip     |
| `rightChildren`   | `ReactNode`             | —           | Trailing content at the very end (a tag, actions, a fold chevron), outside the line's inner padding; not padded     |
| `onClick`         | `() => void`            | —           | Makes the row interactive (`Interactive.Stateless`, `tertiary`); the body never calls it                            |
| `expandable`      | `true`                  | —           | Enables `expanded` and `expandedContent`                                                                            |
| `expanded`        | `boolean`               | —           | Whether the body is open; controlled, the caller owns the state                                                     |
| `expandedContent` | `ReactNode`             | —           | The body, opened in a `Fold` and aligned under the content                                                          |

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

- A row `Section`, 1.75rem tall plus `padding` on each side. Everything but
  `rightChildren` sits in an inner row with another 0.25rem and a 0.25rem gap,
  so tall trailing content cannot stretch the line.
- With `onClick`, the row hovers and presses as a `tertiary` stateless
  surface, and a click anywhere on it but a link calls `onClick`. Put a button
  in `rightChildren` (e.g. a chevron) as its keyboard target: that button's
  click reaches `onClick` too. A button with its own action stops its click
  from bubbling.
- With `expandable`, the body opens below the row in a `Fold`, indented to
  start under the content. It sits outside the row's surface: it does not
  hover, and its clicks and text selection stay its own. A heavy variant tints
  the body too.

## Usage

```tsx
<Line
  variant="error-heavy"
  icon={SvgTerminal}
  title={markdown("Running `npm test`")}
  rightChildren={chevron}
  onClick={toggle}
  expandable
  expanded={open}
  expandedContent={output}
/>
```
