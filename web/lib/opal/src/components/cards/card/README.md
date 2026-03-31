# Card

**Import:** `import { Card, type CardProps } from "@opal/components";`

A plain container component with configurable background, border, padding, and rounding. Uses a simple `<div>` internally with `overflow-clip`.

## Architecture

Padding and rounding are controlled independently:

| `paddingVariant` | Class   |
|------------------|---------|
| `"lg"`           | `p-6`   |
| `"md"`           | `p-4`   |
| `"sm"`           | `p-2`   |
| `"xs"`           | `p-1`   |
| `"2xs"`          | `p-0.5` |

| `roundingVariant` | Class        |
|-------------------|--------------|
| `"sm"`            | `rounded-08` |
| `"md"`            | `rounded-12` |
| `"lg"`            | `rounded-16` |

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `paddingVariant` | `PaddingVariants` | `"sm"` | Padding preset |
| `roundingVariant` | `"sm" \| "md" \| "lg"` | `"md"` | Border-radius preset |
| `backgroundVariant` | `"none" \| "light" \| "heavy"` | `"light"` | Background fill intensity |
| `borderVariant` | `"none" \| "dashed" \| "solid"` | `"none"` | Border style |
| `ref` | `React.Ref<HTMLDivElement>` | — | Ref forwarded to the root div |
| `children` | `React.ReactNode` | — | Card content |

## Usage

```tsx
import { Card } from "@opal/components";

// Default card (light background, no border, sm padding, md rounding)
<Card>
  <h2>Card Title</h2>
  <p>Card content</p>
</Card>

// Large padding + rounding with solid border
<Card paddingVariant="lg" roundingVariant="lg" borderVariant="solid">
  <p>Spacious card</p>
</Card>

// Compact card with solid border
<Card paddingVariant="xs" roundingVariant="sm" borderVariant="solid">
  <p>Compact card</p>
</Card>

// Empty state card
<Card backgroundVariant="none" borderVariant="dashed">
  <p>No items yet</p>
</Card>
```
