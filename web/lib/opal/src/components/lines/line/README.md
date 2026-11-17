# Line

**Import:** `import { Line } from "@opal/components";`

One line of a list or a timeline, or a run card (the `card` flavour, below): an icon, a title and trailing content. A
line is plain unless it gets `onClick`, and it can open a body below it with
`expandable`. With `onClick`, the row and the body are one hover surface, but
only the row toggles it: clicks and text selection in the body never reach
`onClick`. [`LogLine`](../log-line/README.md) shares the same row and surface
(from the internal [`line-base`](../line-base/README.md)) with a log's column
layout.

## Props

| Prop              | Type                    | Default     | Description                                                                                                         |
| ----------------- | ----------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------- |
| `variant`         | `LineVariant`           | `"default"` | Status and weight: colours the icon; heavy also tints the line and its body                                         |
| `padding`         | `0 \| 1`                | `1`         | The outer padding, as a spacing step (`N / 4` rem). `0` for a line inside a container that pads it already          |
| `icon`            | `IconFunctionComponent` | —           | Shown at 1rem with 0.125rem padding                                                                                 |
| `title`           | `string \| RichStr`     | —           | `secondary-action` in `text-03`. Fills the row, on one line, cut with an ellipsis and shown in full in a tooltip     |
| `rightChildren`   | `ReactNode`             | —           | Trailing content at the very end (a tag, actions, a fold chevron), outside the line's inner padding; not padded     |
| `onClick`         | `() => void`            | —           | Makes the row and the body one `tertiary` surface; only a click on the row calls it                     |
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
- With `onClick`, the row and the body hover and press as one `tertiary`
  stateless surface. A click on the row (not on a link) calls `onClick`; a
  click or text selection in the body never does, and the body keeps an
  ordinary cursor. Put a button in `rightChildren` (e.g. a chevron) as its
  keyboard target: that button's click reaches `onClick` too.
- With `expandable`, the body opens below the row in a `Fold`, indented to
  start under the content, with the line's padding on its end and bottom. A
  heavy variant tints the body too.

## Card flavour

`flavour="card"` draws a run card instead of a step: any header with trailing
controls, and the steps in its body. It has 0.25rem of padding, 0.75rem
corners, and a `background-tint-00` fill while `filled`. Its body starts
0.25rem under the header.

| Prop              | Type         | Default | Description                                                                                           |
| ----------------- | ------------ | ------- | ----------------------------------------------------------------------------------------------------- |
| `flavour`         | `"card"`     | —       | Selects the card flavour; `"step"` (the default) is the line above                                    |
| `children`        | `ReactNode`  | —       | The header, e.g. a title that animates                                                                |
| `rightChildren`   | `ReactNode`  | —       | Trailing content at the end of the header, e.g. the fold button                                       |
| `filled`          | `boolean`    | —       | Fills the card, e.g. while its run works or it is open                                                |
| `onClick`         | `() => void` | —       | A click anywhere on the header calls this, and a folded card fills on hover. A button's click reaches it |
| `expandable`, `expanded`, `expandedContent` | | | As above                                                                                             |

```tsx
<Line
  flavour="card"
  filled={open}
  onClick={toggle}
  rightChildren={<Button rightIcon={SvgExpand}>3 steps</Button>}
  expandable
  expanded={open}
  expandedContent={steps}
>
  <TextLoader>Working</TextLoader>
</Line>
```

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
