# Card

**Import:** `import { Card, type CardProps } from "@opal/components";`

A plain container component with configurable background, border, padding, and rounding. Uses a simple `<div>` internally with `overflow-clip`.

## Architecture

Padding and rounding are controlled independently:

| `padding` | Class   |
|-----------|---------|
| `"lg"`    | `p-6`   |
| `"md"`    | `p-4`   |
| `"sm"`    | `p-2`   |
| `"xs"`    | `p-1`   |
| `"2xs"`   | `p-0.5` |
| `"fit"`   | `p-0`   |

| `rounding` | Class        |
|------------|--------------|
| `"xs"`     | `rounded-04` |
| `"sm"`     | `rounded-08` |
| `"md"`     | `rounded-12` |
| `"lg"`     | `rounded-16` |

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `padding` | `PaddingVariants` | `"sm"` | Padding preset |
| `rounding` | `RoundingVariants` | `"md"` | Border-radius preset |
| `background` | `"none" \| "light" \| "heavy"` | `"light"` | Background fill intensity |
| `border` | `"none" \| "dashed" \| "solid"` | `"none"` | Border style |
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
<Card padding="lg" rounding="lg" border="solid">
  <p>Spacious card</p>
</Card>

// Compact card with solid border
<Card padding="xs" rounding="sm" border="solid">
  <p>Compact card</p>
</Card>

// Empty state card
<Card background="none" border="dashed">
  <p>No items yet</p>
</Card>
```
