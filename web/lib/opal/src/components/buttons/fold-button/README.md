# FoldButton

**Import:** `import { FoldButton } from "@opal/components";`

The fold control of a foldable row: a tertiary `Button` with `SvgChevronRight`
that points right while folded and turns down while `open` (a 90° turn over
200ms). Only the icon turns; the button and its hover fill stay put. It sets `aria-expanded`. `Divider`'s foldable header (end chevron), a
timeline step and a connector check use it.

## Props

| Prop          | Type                    | Default | Description                                                         |
| ------------- | ----------------------- | ------- | ------------------------------------------------------------------- |
| `open`        | `boolean`               | —       | Whether the section is open; the chevron turns down                 |
| `size`        | `ContainerSizeVariants` | `"sm"`  | The button's size                                                    |
| `onClick`     | `MouseEventHandler`     | —       | Toggles the section, when the button is the control                 |
| `tooltip`     | `string`                | —       | Hover tooltip                                                        |
| `aria-label`  | `string`                | —       | Accessible name, e.g. "Expand details"                              |
| `aria-hidden` | `boolean`               | —       | For a header that is the control itself                              |
| `tabIndex`    | `number`                | —       | `-1` keeps it out of the Tab order when the header is the Tab stop   |

## Usage

```tsx
<FoldButton
  open={open}
  size="md"
  onClick={toggle}
  aria-label={open ? "Collapse details" : "Expand details"}
/>
```
