# LineItemButton

**Import:** `import { LineItemButton, type LineItemButtonProps } from "@opal/components";`

A composite component that wraps `Interactive.Stateful > Interactive.Container > ContentAction` into a single API. Use it for selectable list rows such as model pickers, menu items, or any row that acts like a button.

## Architecture

```
Interactive.Stateful         <- selectVariant, state, interaction, onClick, href, ref
  └─ Interactive.Container   <- type, width, roundingVariant
       └─ ContentAction      <- withInteractive, paddingVariant="lg"
            ├─ Content       <- icon, title, description, sizePreset, variant, ...
            └─ rightChildren
```

`paddingVariant` is hardcoded to `"lg"` and `withInteractive` is always `true`. These are not exposed as props.

## Props

### Interactive surface

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `selectVariant` | `"select-light" \| "select-heavy"` | `"select-light"` | Interactive select variant |
| `state` | `InteractiveStatefulState` | `"empty"` | Value state (`"empty"`, `"filled"`, `"selected"`) |
| `interaction` | `InteractiveStatefulInteraction` | `"rest"` | JS-controlled interaction state override |
| `onClick` | `MouseEventHandler<HTMLElement>` | — | Click handler |
| `href` | `string` | — | Renders an anchor instead of a div |
| `target` | `string` | — | Anchor target (e.g. `"_blank"`) |
| `group` | `string` | — | Interactive group key |
| `ref` | `React.Ref<HTMLElement>` | — | Forwarded ref |

### Sizing

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `roundingVariant` | `InteractiveContainerRoundingVariant` | `"md"` | Corner rounding preset (height is content-driven) |
| `width` | `WidthVariant` | `"full"` | Container width |
| `type` | `"submit" \| "button" \| "reset"` | `"button"` | HTML button type |
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

All other `ContentAction` / `Content` props (`editable`, `onTitleChange`, `optional`, `auxIcon`, `tag`, etc.) are also passed through. Note: `withInteractive` is always `true` inside `LineItemButton` and cannot be overridden.

## Usage

```tsx
import { LineItemButton } from "@opal/components";

// Simple selectable row
<LineItemButton
  selectVariant="select-heavy"
  state={isSelected ? "selected" : "empty"}
  roundingVariant="sm"
  onClick={handleClick}
  title="gpt-4o"
  sizePreset="main-ui"
  variant="section"
/>

// With right-side action
<LineItemButton
  selectVariant="select-heavy"
  state={isSelected ? "selected" : "empty"}
  onClick={handleClick}
  title="claude-opus-4"
  sizePreset="main-ui"
  variant="section"
  rightChildren={<Tag title="Default" color="blue" />}
/>
```
