# OpenButton

**Import:** `import { OpenButton, type OpenButtonProps } from "@opal/components";`

A trigger button with a built-in chevron that rotates when open. Hardcodes `variant="select"` and delegates to `Button`, adding automatic open-state detection from Radix `data-state`. Designed to work automatically with Radix primitives while also supporting explicit control via the `transient` prop.

## Architecture

```
OpenButton
  └─ Button (variant="select", rightIcon=ChevronIcon)
       └─ Interactive.Base                 <- select variant, transient, selected, disabled, href, onClick
            └─ Interactive.Container       <- height, rounding, padding, border (auto for secondary)
                 └─ div.opal-button.interactive-foreground
                      ├─ div.p-0.5 > Icon?
                      ├─ <span>?                   .opal-button-label
                      └─ div.p-0.5 > ChevronIcon   .opal-open-button-chevron
```

- **Always uses `variant="select"`.** OpenButton omits `variant` and `subvariant` from its own props; it hardcodes `variant="select"` and only exposes `InteractiveBaseSelectVariantProps` (`subvariant?: "light" | "heavy"`, `selected?: boolean`).
- **`transient` controls both the chevron and the hover visual state.** When `transient` is true (explicitly or via Radix `data-state="open"`), the chevron rotates 180° and the `Interactive.Base` hover background activates. There is no separate `open` prop.
- **Open-state detection** is dual-resolution: the explicit `transient` prop takes priority; otherwise the component reads `data-state="open"` injected by Radix triggers (e.g. `Popover.Trigger`).
- **Chevron rotation** is CSS-driven via `.interactive[data-transient="true"] .opal-open-button-chevron { rotate: -180deg }`. The `ChevronIcon` is a stable named component (not an inline function) to preserve React element identity across renders, ensuring CSS transitions fire correctly.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `subvariant` | `"light" \| "heavy"` | `"light"` | Select subvariant. `"heavy"` shows a tinted background when selected. |
| `selected` | `boolean` | `false` | Switches foreground to action-link colours |
| `transient` | `boolean` | -- | Forces transient (hover) visual state and chevron rotation. Falls back to Radix `data-state="open"` when omitted. |
| `icon` | `IconFunctionComponent` | -- | Left icon component |
| `children` | `string` | -- | Content between icon and chevron |
| `size` | `SizeVariant` | `"default"` | Size preset controlling height, rounding, and padding |
| `tooltip` | `string` | -- | Tooltip text shown on hover |
| `tooltipSide` | `TooltipSide` | `"top"` | Which side the tooltip appears on |
| `disabled` | `boolean` | `false` | Disables the button |
| `href` | `string` | -- | URL; renders an `<a>` wrapper |
| `onClick` | `MouseEventHandler<HTMLElement>` | -- | Click handler |
| _...and all other `ButtonProps` (minus variant props) / `InteractiveBaseProps`_ | | | `group`, `static`, `ref`, etc. |

## Usage examples

```tsx
import { OpenButton } from "@opal/components";
import { SvgFilter } from "@opal/icons";

// Basic usage with Radix Popover (auto-detects open state from data-state)
<Popover.Trigger asChild>
  <OpenButton>
    Select option
  </OpenButton>
</Popover.Trigger>

// Explicit transient control (chevron rotates AND button shows hover state)
<OpenButton transient={isExpanded} onClick={toggle}>
  Advanced settings
</OpenButton>

// With selected state (action-link foreground)
<OpenButton selected={isActive} transient={isExpanded} onClick={toggle}>
  Active filter
</OpenButton>

// With left icon and heavy subvariant (tinted background when selected)
<OpenButton icon={SvgFilter} subvariant="heavy" selected={isActive}>
  Filters
</OpenButton>

// Compact sizing
<OpenButton size="compact">
  More
</OpenButton>

// With tooltip
<OpenButton tooltip="Expand filters" icon={SvgFilter}>
  Filters
</OpenButton>
```
