# Disabled

**Import:** `import { Disabled } from "@opal/core";`

Wrapper component that applies baseline disabled CSS (opacity, cursor, pointer-events) to its
children. Renders a `<div>` with the `data-opal-disabled` attribute so styling cascades into all
descendants. Works with any children — DOM elements, React components, or fragments.

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
| `.opal-disabled` | `self-stretch` (wrapper stretches to fill parent cross-axis) |
| `[data-opal-disabled]` | `cursor-not-allowed`, `select-none`, `pointer-events: none` |
| `[data-opal-disabled]:not(.interactive)` | `opacity-50` (non-Interactive elements only) |
| `[data-opal-disabled].interactive` | `pointer-events: auto` (Interactive elements handle their own disabled colors) |
| `[data-opal-disabled][data-allow-click]` | `pointer-events: auto` |

## Usage

```tsx
// Basic — disables children visually and blocks pointer events
<Disabled disabled={!canSubmit}>
  <Card>Content</Card>
</Disabled>

// With tooltip — explains why the section is disabled
<Disabled disabled={!canSubmit} tooltip="Complete the form first">
  <Card>Content</Card>
</Disabled>

// With allowClick — keeps pointer events for custom handling
<Disabled disabled={isProcessing} allowClick>
  <MyInputBar />
</Disabled>
```
