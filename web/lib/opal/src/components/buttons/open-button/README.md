# OpenButton

**Import:** `import { OpenButton, type OpenButtonProps } from "@opal/components";`

A trigger button with a built-in chevron that rotates when open. Hardcodes `variant="select-heavy"` and delegates to `Interactive.Stateful`, adding automatic open-state detection from Radix `data-state`. Designed to work automatically with Radix primitives while also supporting explicit control via the `interaction` prop.

## Relationship to SelectButton

OpenButton is structurally near-identical to `SelectButton` — both share the same call stack:

```
Interactive.Stateful → Interactive.Container → content row (icon + label + trailing icon)
```

OpenButton is a **tighter, specialized use-case** of SelectButton:

- It hardcodes `variant="select-heavy"` (SelectButton exposes `variant`)
- It adds a built-in chevron with CSS-driven rotation (SelectButton has no chevron)
- It auto-detects Radix `data-state="open"` to derive `interaction` (SelectButton has no Radix awareness)
- It does not support `rightIcon` (SelectButton does)

Both components support `foldable` using the same pattern: `interactive-foldable-host` class + `Interactive.Foldable` wrapper around the label and trailing icon. When foldable, the left icon stays visible while the rest collapses. If you change the foldable implementation in one, update the other to match.

If you need a general-purpose stateful toggle, use `SelectButton`. If you need a popover/dropdown trigger with a chevron, use `OpenButton`.

## Architecture

```
Interactive.Stateful           <- variant="select-heavy", interaction, state, disabled, onClick
  └─ Interactive.Container     <- height, rounding, padding (from `size`)
       └─ div.opal-button.interactive-foreground [.interactive-foldable-host]
            ├─ div > Icon?                 (interactive-foreground-icon)
            ├─ [Foldable]?                 (wraps label + chevron when foldable)
            │    ├─ <span>?                .opal-button-label
            │    └─ div > ChevronIcon      .opal-open-button-chevron
            └─ <span>? / ChevronIcon       (non-foldable)
```

- **`interaction` controls both the chevron and the hover visual state.** When `interaction` is `"hover"` (explicitly or via Radix `data-state="open"`), the chevron rotates 180° and the hover background activates.
- **Open-state detection** is dual-resolution: the explicit `interaction` prop takes priority; otherwise the component reads `data-state="open"` injected by Radix triggers (e.g. `Popover.Trigger`).
- **Chevron rotation** is CSS-driven via `.interactive[data-interaction="hover"] .opal-open-button-chevron { rotate: -180deg }`. The `ChevronIcon` is a stable named component (not an inline function) to preserve React element identity across renders.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `state` | `"empty" \| "filled" \| "selected"` | `"empty"` | Current value state |
| `interaction` | `"rest" \| "hover" \| "active"` | auto | JS-controlled interaction override. Falls back to Radix `data-state="open"` when omitted. |
| `icon` | `IconFunctionComponent` | — | Left icon component |
| `children` | `string` | — | Content between icon and chevron |
| `foldable` | `boolean` | `false` | When `true`, label + chevron collapse when not hovered |
| `size` | `SizeVariant` | `"lg"` | Size preset controlling height, rounding, and padding |
| `width` | `WidthVariant` | — | Width preset |
| `tooltip` | `string` | — | Tooltip text shown on hover |
| `tooltipSide` | `TooltipSide` | `"top"` | Which side the tooltip appears on |
| `disabled` | `boolean` | `false` | Disables the button |

## Usage

```tsx
import { OpenButton } from "@opal/components";
import { SvgFilter } from "@opal/icons";

// Basic usage with Radix Popover (auto-detects open state)
<Popover.Trigger asChild>
  <OpenButton>Select option</OpenButton>
</Popover.Trigger>

// Explicit interaction control
<OpenButton interaction={isExpanded ? "hover" : "rest"} onClick={toggle}>
  Advanced settings
</OpenButton>

// With left icon
<OpenButton icon={SvgFilter} state="filled">
  Filters
</OpenButton>
```
