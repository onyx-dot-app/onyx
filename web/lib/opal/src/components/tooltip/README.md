# Tooltip

**Import:** `import { Tooltip } from "@opal/components";`

A minimal tooltip wrapper that shows content on hover. When `tooltip` is `undefined`, children
are returned as-is with no wrapping. Uses Radix Tooltip primitives internally.

Supports both uncontrolled (default hover behavior) and controlled (`open` + `onOpenChange`)
modes.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `tooltip` | `ReactNode \| RichStr` | — | Tooltip content. `string`/`RichStr` rendered via `Text`; `ReactNode` rendered as-is. `undefined` = no tooltip. |
| `side` | `"top" \| "bottom" \| "left" \| "right"` | `"right"` | Which side the tooltip appears on |
| `align` | `"start" \| "center" \| "end"` | `"center"` | Alignment along the tooltip's side axis |
| `open` | `boolean` | — | Controlled open state. When omitted, uses default hover behavior. |
| `onOpenChange` | `(open: boolean) => void` | — | Callback when open state changes. Use with `open` for controlled mode. |
| `delayDuration` | `number` | — | Delay in ms before the tooltip appears on hover |
| `sideOffset` | `number` | `4` | Distance in pixels between the trigger and the tooltip |

## Usage

```tsx
import { Tooltip } from "@opal/components";

// Uncontrolled (default hover behavior)
<Tooltip tooltip="Delete this item">
  <Button icon={SvgTrash} />
</Tooltip>

// Controlled
const [isOpen, setIsOpen] = useState(false);
<Tooltip tooltip="Details" open={isOpen} onOpenChange={setIsOpen}>
  <Button icon={SvgInfo} />
</Tooltip>

// Conditional — no tooltip when undefined
<Tooltip tooltip={isDisabled ? "Not available" : undefined}>
  <Button>Action</Button>
</Tooltip>
```

## Notes

- Children must be a single element compatible with Radix `asChild` (DOM element or a component
  that forwards refs).
- `string` and `RichStr` content is rendered via `Text font="secondary-body" color="inherit"`.
- `ReactNode` content is rendered as-is for custom tooltip layouts.
- The `opal-tooltip` CSS class provides z-indexing, animations, and a `max-width: 20rem` cap.
