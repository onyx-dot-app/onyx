# Divider

**Import:** `import { Divider } from "@opal/components";`

A horizontal rule that optionally displays a title, description, or foldable content section.

## Props

The component uses a discriminated union with four variants. `title` and `description` are mutually exclusive; `foldable` requires `title`.

### Bare divider

A plain line with no title or description.

| Prop | Type | Default | Description |
|---|---|---|---|
| `orientation` | `"horizontal" \| "vertical"` | `"horizontal"` | Direction of the line |
| `paddingParallel` | `PaddingVariants` | `"sm"` | Padding along the line direction (0.5rem) |
| `paddingPerpendicular` | `PaddingVariants` | `"xs"` | Padding perpendicular to the line (0.25rem) |

### Titled divider

| Prop | Type | Default | Description |
|---|---|---|---|
| `title` | `string \| RichStr` | **(required)** | Label to the left of the line |

### Described divider

| Prop | Type | Default | Description |
|---|---|---|---|
| `description` | `string \| RichStr` | **(required)** | Text below the line |

### Foldable divider

| Prop | Type | Default | Description |
|---|---|---|---|
| `title` | `string \| RichStr` | **(required)** | Label to the left of the line |
| `foldable` | `true` | **(required)** | Enables fold/expand behavior |
| `open` | `boolean` | — | Controlled open state |
| `defaultOpen` | `boolean` | `false` | Uncontrolled initial open state |
| `onOpenChange` | `(open: boolean) => void` | — | Callback when toggled |
| `children` | `ReactNode` | — | Content revealed when open |

## Usage Examples

```tsx
import { Divider } from "@opal/components";

// Plain horizontal line
<Divider />

// Vertical line
<Divider orientation="vertical" />

// No padding
<Divider paddingParallel="fit" paddingPerpendicular="fit" />

// Custom padding
<Divider paddingParallel="lg" paddingPerpendicular="sm" />

// With title
<Divider title="Advanced" />

// With description
<Divider description="Additional configuration options." />

// Foldable
<Divider title="Advanced Options" foldable>
  <p>Hidden content here</p>
</Divider>

// Controlled foldable
const [open, setOpen] = useState(false);
<Divider title="Details" foldable open={open} onOpenChange={setOpen}>
  <p>Controlled content</p>
</Divider>
```
