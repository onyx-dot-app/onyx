# Tooltip

**Import:** `import { Tooltip } from "@opal/components";`

A minimal tooltip wrapper that shows content on hover. When `tooltip` is `undefined`, children
are returned as-is with no wrapping. Uses Radix Tooltip primitives internally.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `tooltip` | `ReactNode \| RichStr` | — | Tooltip content. `string`/`RichStr` rendered via `Text`; `ReactNode` rendered as-is. `undefined` = no tooltip. |
| `tooltipSide` | `"top" \| "bottom" \| "left" \| "right"` | `"right"` | Which side the tooltip appears on |

## Usage

```tsx
import { Tooltip } from "@opal/components";

// Basic string tooltip
<Tooltip tooltip="Delete this item">
  <Button icon={SvgTrash} />
</Tooltip>

// With markdown
<Tooltip tooltip={markdown("Supports **bold** text")}>
  <Button icon={SvgInfo} />
</Tooltip>

// No tooltip — children passed through
<Tooltip tooltip={undefined}>
  <Button>No tooltip</Button>
</Tooltip>
```

## Notes

- Children must be a single element compatible with Radix `asChild` (DOM element or a component
  that forwards refs).
- The tooltip uses `Text font="secondary-body" color="inherit"` for consistent styling.
- The `opal-tooltip` CSS class provides z-indexing, animations, and a `max-width: 20rem` cap.
