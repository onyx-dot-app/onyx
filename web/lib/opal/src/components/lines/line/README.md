# Line

**Import:** `import { Line } from "@opal/components";`

A run card: a header with trailing controls, and a body below it that opens
and closes. It has 0.25rem of padding, 0.75rem corners, and a
`background-tint-00` fill while `filled`. Its body starts right under the
header. A `Line` inside another `Line`'s body (a step in a run card) has no
padding of its own, so its title lines up with the outer card's.

It is built on [`Collapsible`](../../collapsible/README.md)'s parts: the
header is a `Collapsible.Header` and the body a `Collapsible.Content`, so
clicks and text selection in the body never reach `onClick`.
[`LogLine`](../log-line/README.md) shares its frame (from the internal
[`line-base`](../line-base/README.md)).

## Props

| Prop                                        | Type                    | Default          | Description                                                                                                                                                                                 |
| ------------------------------------------- | ----------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `children`                                  | `ReactNode`             | —                | The header: any content. Or use `title` instead                                                                                                                                             |
| `title`                                     | `string \| RichStr`     | —                | The card's own title, laid out as `Content` lays out an inline title. A new title (or `titleKey`) animates the old one out; a header that toggles the card darkens it and its icon on hover |
| `icon`                                      | `IconFunctionComponent` | —                | The title's icon, in a box one line tall                                                                                                                                                    |
| `titleKey`                                  | `React.Key`             | the title's text | The title's identity: a new key swaps the title; the same key updates it in place                                                                                                           |
| `shimmer`                                   | `boolean`               | `false`          | Shimmers the title, e.g. while the card's work runs                                                                                                                                         |
| `rightChildren`                             | `ReactNode`             | —                | Trailing content at the end of the header, before the fold button                                                                                                                           |
| `filled`                                    | `boolean`               | —                | Fills the card, e.g. while its run works or it is open                                                                                                                                      |
| `onClick`                                   | `() => void`            | —                | The header toggles the card, and a folded card fills on hover. Without it, the card cannot fold                                                                                             |
| `foldLabel`                                 | `string`                | —                | The header's fold button label, e.g. "3 steps", with `SvgExpand` / `SvgFold`; it lights up while the header is hovered. Without it, a card with `onClick` shows a chevron                   |
| `expandable`                                | `true`                  | —                | Enables `expanded` and `expandedContent`                                                                                                                                                    |
| `expanded`                                  | `boolean`               | —                | Whether the body is open; controlled, the caller owns the state                                                                                                                             |
| `expandedContent`                           | `ReactNode`             | —                | The body, opened in a `Fold`, flush with the card's padding                                                                                                                                 |

## Usage

```tsx
<Line
  icon={SvgSparkle}
  title="Doing work"
  shimmer={running}
  filled={running || open}
  onClick={toggle}
  expandable
  expanded={open}
  expandedContent={steps}
/>
```
