# OpenButton

**Import:** `import { OpenButton, type OpenButtonProps } from "@opal/components";`

A trigger button with a built-in chevron that rotates when open. Built on top of `Button`, it adds an `open` prop that is independent of the `transient` visual state. Designed to work automatically with Radix primitives while also supporting explicit control.

## Architecture

```
Button                                <- all ButtonProps (variant, subvariant, transient, icon, size, etc.)
  └─ Interactive.Base                 <- variant/subvariant, transient, disabled, href, onClick
       └─ Interactive.Container       <- height, rounding, padding, border (auto for secondary)
            └─ div.opal-button.interactive-foreground
                 ├─ div.p-0.5 > Icon?
                 ├─ <span>?                   .opal-button-label
                 └─ div.p-0.5 > SvgChevronDownSmall  .opal-open-button-chevron (+-rotate-180)
```

- **`open` vs `transient` are independent.** The `open` prop (or Radix `data-state="open"`) controls only the chevron rotation. The `transient` prop controls the `Interactive.Base` visual state (background/foreground colors). A button can be open without being transient, or transient without being open.
- **Open-state detection** is dual-resolution: the `open` prop takes priority; otherwise the component reads `data-state="open"` injected by Radix triggers (e.g. `Popover.Trigger`).
- **Delegates to Button.** OpenButton extends `ButtonProps` with an additional `open` prop and injects the chevron as `rightIcon`. All other props (`variant`, `subvariant`, `transient`, `size`, `tooltip`, etc.) pass through to Button unchanged.
- **Chevron rotation** is applied directly via the `-rotate-180` Tailwind class when open. The `.opal-open-button-chevron` base class provides a smooth `transition-transform` animation.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `open` | `boolean` | -- | Controls chevron rotation. Falls back to Radix `data-state="open"` when omitted. |
| `variant` | `"default" \| "action" \| "danger" \| "none" \| "select"` | `"default"` | Top-level color variant |
| `subvariant` | Depends on `variant` | `"primary"` | Color subvariant. `"secondary"` automatically renders a border. |
| `icon` | `IconFunctionComponent` | -- | Left icon component |
| `children` | `string` | -- | Content between icon and chevron |
| `size` | `SizeVariant` | `"default"` | Size preset controlling height, rounding, and padding |
| `tooltip` | `string` | -- | Tooltip text shown on hover |
| `tooltipSide` | `TooltipSide` | `"top"` | Which side the tooltip appears on |
| `selected` | `boolean` | `false` | Switches foreground to action-link colours (only available with `variant="select"`) |
| `transient` | `boolean` | `false` | Forces transient (hover) visual state (independent of chevron rotation) |
| `disabled` | `boolean` | `false` | Disables the button |
| `href` | `string` | -- | URL; renders an `<a>` wrapper |
| `onClick` | `MouseEventHandler<HTMLElement>` | -- | Click handler |
| _...and all other `ButtonProps` / `InteractiveBaseProps`_ | | | `group`, `static`, `ref`, etc. |

## Usage examples

```tsx
import { OpenButton } from "@opal/components";
import { SvgFilter } from "@opal/icons";

// Basic usage with Radix Popover (auto-detects open state from data-state)
<Popover.Trigger asChild>
  <OpenButton variant="default" subvariant="ghost">
    Select option
  </OpenButton>
</Popover.Trigger>

// Explicit open control (chevron rotates, but button is NOT visually transient)
<OpenButton open={isExpanded} onClick={toggle}>
  Advanced settings
</OpenButton>

// Open AND transient (chevron rotates AND button shows hover visual state)
<OpenButton open={isExpanded} transient={isExpanded} onClick={toggle}>
  Advanced settings
</OpenButton>

// With left icon and secondary subvariant (auto border)
<OpenButton icon={SvgFilter} variant="default" subvariant="secondary">
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
