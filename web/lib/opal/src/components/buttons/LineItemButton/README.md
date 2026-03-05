# LineItemButton

A composite component that wraps `Interactive.Base(select) > Interactive.Container > ContentAction` into a single, ergonomic API. Use it for selectable list rows such as model pickers, menu items, or any row that acts like a button.

## Usage

```tsx
import { LineItemButton } from "@opal/components";
import Checkbox from "@/refresh-components/inputs/Checkbox";

<LineItemButton
  prominence="heavy"
  selected={isSelected}
  size="md"
  onClick={handleClick}
  title="gpt-4o"
  sizePreset="main-ui"
  variant="section"
  leftChildren={<Checkbox checked={isSelected} />}
/>
```

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `prominence` | `"light" \| "heavy"` | `"light"` | Interactive select prominence |
| `selected` | `boolean` | — | Whether the item appears selected |
| `disabled` | `boolean` | — | Disables interaction |
| `size` | `SizeVariant` | `"lg"` | Container height |
| `width` | `WidthVariant` | `"full"` | Container width |
| `title` | `string` | **(required)** | Row label |
| `leftChildren` | `ReactNode` | — | Content before the label (e.g. Checkbox) |
| `rightChildren` | `ReactNode` | — | Content after the label (e.g. action button) |

All other `ContentAction` props (`icon`, `description`, `sizePreset`, `variant`, etc.) are passed through.
