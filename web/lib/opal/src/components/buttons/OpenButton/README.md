# OpenButton

**Import:** `import { OpenButton, type OpenButtonProps } from "@opal/components";`

A trigger button with a built-in chevron that rotates when open. Hardcodes `variant="select"` and delegates to `Button`, adding automatic open-state detection from Radix `data-state`.

## Architecture

```
OpenButton
  └─ Button (variant="select", rightIcon=ChevronIcon)
       └─ Interactive.Base        <- select variant, transient, selected, disabled, href, onClick
            └─ Interactive.Container
                 └─ div.opal-button.interactive-foreground
                      ├─ div > Icon?
                      ├─ <span>?              .opal-button-label
                      └─ div > ChevronIcon    .opal-open-button-chevron
```

- **Always uses `variant="select"`.** Only exposes `InteractiveBaseSelectVariantProps` (`prominence?: "light" | "heavy"`, `selected?: boolean`).
- **`transient` controls both the chevron and the hover visual state.** When `transient` is true (explicitly or via Radix `data-state="open"`), the chevron rotates 180deg.
- **Open-state detection** is dual-resolution: explicit `transient` prop takes priority; otherwise reads `data-state="open"` from Radix triggers.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `prominence` | `"light" \| "heavy"` | `"light"` | Select prominence |
| `selected` | `boolean` | `false` | Selected foreground state |
| `transient` | `boolean` | — | Forces transient state + chevron rotation. Falls back to Radix `data-state`. |
| `icon` | `IconFunctionComponent` | — | Left icon component |
| `children` | `string` | — | Content between icon and chevron |
| `size` | `SizeVariant` | `"lg"` | Size preset |
| `type` | `"submit" \| "button" \| "reset"` | `"button"` | HTML button type |
| `width` | `WidthVariant` | `"auto"` | Width preset |
| `foldable` | `boolean` | `false` | Foldable mode (inherited from Button) |
| `tooltip` | `string` | — | Tooltip text shown on hover |
| `tooltipSide` | `TooltipSide` | `"top"` | Tooltip side |
| `href` | `string` | — | URL; renders an `<a>` wrapper |
| `onClick` | `MouseEventHandler<HTMLElement>` | — | Click handler |
| `ref` | `React.Ref<HTMLElement>` | — | Ref forwarded via Button > Interactive.Base |

## Usage examples

```tsx
import { OpenButton } from "@opal/components";
import { SvgFilter } from "@opal/icons";

// With Radix Popover (auto-detects open state)
<Popover.Trigger asChild>
  <OpenButton>Select option</OpenButton>
</Popover.Trigger>

// Explicit transient control
<OpenButton transient={isExpanded} onClick={toggle}>
  Advanced settings
</OpenButton>

// With left icon and heavy prominence
<OpenButton icon={SvgFilter} prominence="heavy" selected={isActive}>
  Filters
</OpenButton>

// Small sizing
<OpenButton size="sm">More</OpenButton>
```
