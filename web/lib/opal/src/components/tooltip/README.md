# Tooltip

**Import:** `import { Tooltip } from "@opal/components";`

A minimal tooltip wrapper that shows content on hover. When `tooltip` is `undefined`, children
are returned as-is with no wrapping. Uses Radix Tooltip primitives internally.

Hover is Radix's to track. There is no controlled `open` — use `suppressed` to turn a tooltip
off while keeping the trigger mounted.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `tooltip` | `ReactNode \| RichStr` | — | Tooltip content. `string`/`RichStr` rendered via `Text`; `ReactNode` rendered as-is. `undefined` = no tooltip. |
| `side` | `"top" \| "bottom" \| "left" \| "right"` | `"right"` | Which side the tooltip appears on |
| `align` | `"start" \| "center" \| "end"` | `"center"` | Alignment along the tooltip's side axis |
| `suppressed` | `boolean` | `false` | Shows nothing on hover, but keeps the trigger mounted |
| `delayDuration` | `number` | — | Delay in ms before the tooltip appears on hover |
| `sideOffset` | `number` | `4` | Distance in pixels between the trigger and the tooltip |

## Usage

```tsx
import { Tooltip } from "@opal/components";

<Tooltip tooltip="Delete this item">
  <Button icon={SvgTrash} />
</Tooltip>

// Conditional — no tooltip when undefined
<Tooltip tooltip={isDisabled ? "Not available" : undefined}>
  <Button>Action</Button>
</Tooltip>

// Suppressed — same tree, nothing on hover
<Tooltip tooltip="Rename" suppressed={!isCollapsed}>
  <Button icon={SvgEdit} />
</Tooltip>
```

## Notes

- Children must be a single element compatible with Radix `asChild` (DOM element or a component
  that forwards refs).
- `string` and `RichStr` content is rendered via `Text font="secondary-body" color="inherit"`.
- `ReactNode` content is rendered as-is for custom tooltip layouts.
- The `opal-tooltip` CSS class provides z-indexing, animations, and a `max-width: 20rem` cap.
- The surface is dark in both themes, so content renders inside a `dark` theme scope. Adaptive
  tokens (`text-03` and friends) resolve to their dark values; `text-inverted-*` resolves
  backwards and is wrong here.
- There is no controlled `open`. Radix drops any open change that already matches the value it
  was given, so a caller that gates `open` on something other than the hover state stops hearing
  about closes and holds a hover that ended.
- Dropping `tooltip` returns children bare. The tree shape changes, so the children remount. Use
  `suppressed` when the children hold state that is tied to the node: a ref that a measurement or
  an observer reads, a running animation, or focus. A remount costs nothing otherwise, so a plain
  conditional stays right for the usual "no tooltip in this state" case.
