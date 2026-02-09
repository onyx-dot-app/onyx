# OpenButton

**Import:** `import { OpenButton, type OpenButtonProps } from "@opal/components";`

A trigger button with a built-in chevron that rotates when `selected` is true (or when a Radix parent injects `data-state="open"`). Designed to work automatically with Radix primitives while also supporting explicit control.

## Architecture

```
Interactive.Base            <- variant/subvariant, selected, disabled, href, onClick, group, static
  └─ Interactive.Container  <- height, rounding, padding (derived from `size`), border
       └─ div.opal-open-button.interactive-foreground  <- full-width flexbox row
            ├─ Icon?               .opal-open-button-icon     (1rem x 1rem, shrink-0)
            ├─ <div>               .opal-open-button-content  (flex-1, min-w-0)
            └─ SvgChevronDownSmall .opal-open-button-chevron  (rotates 180° when selected)
```

- **Selected-state detection** is dual-resolution: the `selected` prop takes priority; otherwise the component reads `data-state="open"` injected by Radix triggers (e.g. `Popover.Trigger`). The `selected` prop drives both the `Interactive.Base` visual state and the chevron rotation.
- **Sizing** uses the shared `SizeVariant` type (same as Button), mapping to Container height/rounding/padding presets.
- **Colors** are handled by `Interactive.Base` -- the `.interactive-foreground` class ensures icon, text, and chevron all track the current state color.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `variant` | `"default" \| "action" \| "danger" \| "none" \| "select"` | `"default"` | Top-level color variant |
| `subvariant` | Depends on `variant` | `"primary"` | Color subvariant |
| `icon` | `IconFunctionComponent` | -- | Left icon component |
| `children` | `string` | -- | Content between icon and chevron |
| `border` | `boolean` | `false` | Applies a 1px border to the container |
| `size` | `SizeVariant` | `"default"` | Size preset controlling height, rounding, and padding |
| `tooltip` | `string` | -- | Tooltip text shown on hover |
| `tooltipSide` | `TooltipSide` | `"top"` | Which side the tooltip appears on |
| `selected` | `boolean` | `false` | Forces selected visual state and rotates chevron |
| `disabled` | `boolean` | `false` | Disables the button |
| `href` | `string` | -- | URL; renders an `<a>` wrapper |
| `onClick` | `MouseEventHandler<HTMLElement>` | -- | Click handler |
| _...and all other `InteractiveBaseProps`_ | | | `group`, `static`, `ref`, etc. |

## Usage examples

```tsx
import { OpenButton } from "@opal/components";
import { SvgFilter } from "@opal/icons";

// Basic usage with Radix Popover (auto-detects open state)
<Popover.Trigger asChild>
  <OpenButton variant="default" subvariant="ghost" border>
    Select option
  </OpenButton>
</Popover.Trigger>

// Explicit selected control
<OpenButton selected={isExpanded} onClick={toggle}>
  Advanced settings
</OpenButton>

// With left icon
<OpenButton icon={SvgFilter} variant="default" subvariant="secondary" border>
  Filters
</OpenButton>

// Compact sizing
<OpenButton size="compact">
  More
</OpenButton>

// With tooltip
<OpenButton tooltip="Expand filters" icon={SvgFilter} border>
  Filters
</OpenButton>
```
