# LineItemButton

**Import:** `import { LineItemButton, type LineItemButtonProps } from "@opal/components";`

A composite component that wraps `Interactive.Base(select) > Interactive.Container > ContentAction` into a single API. Use it for selectable list rows such as model pickers, menu items, or any row that acts like a button.

## Architecture

```
Interactive.Base (variant="select")  <- prominence, selected, onClick, href, ref
  └─ Interactive.Container           <- type, width, size, rounding (derived from size)
       └─ ContentAction              <- withInteractive, paddingVariant="fit", widthVariant="full"
            ├─ Content               <- icon, title, description, sizePreset, variant, ...
            └─ rightChildren
```

`paddingVariant` is hardcoded to `"fit"` (Container owns the padding) and `widthVariant` is hardcoded to `"full"`. These are not exposed as props.

## Props

### Interactive surface (always `variant="select"`)

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `prominence` | `"light" \| "heavy"` | `"light"` | Interactive select prominence |
| `selected` | `boolean` | — | Whether the item appears selected |
| `onClick` | `MouseEventHandler<HTMLElement>` | — | Click handler |
| `href` | `string` | — | Renders an anchor instead of a div |
| `target` | `string` | — | Anchor target (e.g. `"_blank"`) |
| `group` | `string` | — | Interactive group key |
| `transient` | `boolean` | — | Transient interactive state |
| `ref` | `React.Ref<HTMLElement>` | — | Forwarded ref |

### Sizing

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `size` | `SizeVariant` | `"lg"` | Container height |
| `width` | `WidthVariant` | `"full"` | Container width |
| `type` | `"submit" \| "button" \| "reset"` | — | HTML button type |
| `tooltip` | `string` | — | Tooltip text shown on hover |
| `tooltipSide` | `TooltipSide` | `"top"` | Tooltip side |

### Content (pass-through to ContentAction)

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `title` | `string` | **(required)** | Row label |
| `icon` | `IconFunctionComponent` | — | Left icon |
| `description` | `string` | — | Description below the title |
| `sizePreset` | `SizePreset` | `"headline"` | Content size preset |
| `variant` | `ContentVariant` | `"heading"` | Content layout variant |
| `rightChildren` | `ReactNode` | — | Content after the label (e.g. action button) |

All other `ContentAction` / `Content` props (`editable`, `onTitleChange`, `optional`, `auxIcon`, `tag`, `withInteractive`, etc.) are also passed through.

## Usage

```tsx
import { LineItemButton } from "@opal/components";

// Simple selectable row
<LineItemButton
  prominence="heavy"
  selected={isSelected}
  size="md"
  onClick={handleClick}
  title="gpt-4o"
  sizePreset="main-ui"
  variant="section"
/>

// With right-side action
<LineItemButton
  prominence="heavy"
  selected={isSelected}
  onClick={handleClick}
  title="claude-opus-4"
  sizePreset="main-ui"
  variant="section"
  rightChildren={<Tag title="Default" color="blue" />}
/>
```
