# Disabled

**Import:** `import { Disabled } from "@opal/core";`

Wrapper component that applies baseline disabled CSS (opacity, cursor, pointer-events) to its
child element. Uses Radix `Slot` to merge props onto the single child element without adding any
DOM node. Supports an optional `tooltip` prop and `allowClick` to re-enable pointer events.

**Note:** The child must be a single DOM element (not a React component). Radix `Slot` cannot
merge data-attributes onto React component children.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `disabled` | `boolean` | `false` | Applies disabled styling when truthy |
| `allowClick` | `boolean` | `false` | Re-enables pointer events while keeping disabled visuals |
| `tooltip` | `string \| RichStr` | — | Tooltip shown on hover when disabled (implies `allowClick`). Supports `markdown()`. |
| `tooltipSide` | `"top" \| "bottom" \| "left" \| "right"` | `"right"` | Which side the tooltip appears on |

## CSS behavior

| Selector | Effect |
|----------|--------|
| `[data-opal-disabled]` | `cursor-not-allowed`, `select-none`, `pointer-events: none` |
| `[data-opal-disabled]:not(.interactive)` | `opacity-50` (non-Interactive elements only) |
| `[data-opal-disabled].interactive` | `pointer-events: auto` (Interactive elements handle their own disabled colors) |
| `[data-opal-disabled][data-allow-click]` | `pointer-events: auto` |

## Usage

```tsx
// Basic — disables children visually and blocks pointer events
<Disabled disabled={!canSubmit}>
  <div>Content</div>
</Disabled>

// With tooltip — explains why the section is disabled
<Disabled disabled={!canSubmit} tooltip="Complete the form first">
  <div>Content</div>
</Disabled>

// With allowClick — keeps pointer events for custom handling
<Disabled disabled={isProcessing} allowClick>
  <div>...</div>
</Disabled>
```
