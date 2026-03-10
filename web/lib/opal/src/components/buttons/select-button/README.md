# SelectButton

**Import:** `import { SelectButton, type SelectButtonProps } from "@opal/components";`

A stateful button for togglable selections — the stateful counterpart to `Button`. Built on `Interactive.Stateful` > `Interactive.Container`.

## Relationship to OpenButton

SelectButton and `OpenButton` are structurally near-identical — both share the same call stack:

```
Interactive.Stateful → Interactive.Container → content row (icon + label + trailing icon)
```

`OpenButton` is a **tighter, specialized use-case** of SelectButton:

- OpenButton hardcodes `variant="select-heavy"` (SelectButton exposes `variant`)
- OpenButton adds a built-in chevron with CSS-driven rotation (SelectButton has no chevron)
- OpenButton auto-detects Radix `data-state="open"` to derive `interaction` (SelectButton has no Radix awareness)
- OpenButton does not support `foldable` or `rightIcon` (SelectButton does)

Use SelectButton for general-purpose stateful toggles. Use `OpenButton` for popover/dropdown triggers with a chevron.

## Architecture

```
Interactive.Stateful           <- variant, state, interaction, disabled, onClick
  └─ Interactive.Container     <- height, rounding, padding (from `size`)
       └─ div.opal-select-button.interactive-foreground
            ├─ Icon?           (interactive-foreground-icon)
            ├─ [Foldable]?     (wraps label + rightIcon when foldable)
            │    ├─ <span>     .opal-select-button-label
            │    └─ RightIcon?
            └─ <span>? / RightIcon?  (non-foldable)
```

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `variant` | `"select-light" \| "select-heavy" \| "sidebar"` | `"select-heavy"` | Stateful color variant |
| `state` | `"empty" \| "filled" \| "selected"` | `"empty"` | Current value state |
| `interaction` | `"rest" \| "hover" \| "active"` | `"rest"` | JS-controlled interaction override |
| `icon` | `IconFunctionComponent` | — | Left icon |
| `children` | `string` | — | Label text |
| `rightIcon` | `IconFunctionComponent` | — | Right icon |
| `foldable` | `boolean` | `false` | When `true`, label + rightIcon collapse when not hovered |
| `size` | `SizeVariant` | `"lg"` | Size preset |
| `width` | `WidthVariant` | — | Width preset |
| `tooltip` | `string` | — | Tooltip text |
| `tooltipSide` | `TooltipSide` | `"top"` | Tooltip placement |
| `disabled` | `boolean` | `false` | Disables the button |

## Usage

```tsx
import { SelectButton } from "@opal/components";
import { SvgStar } from "@opal/icons";

// Basic toggle
<SelectButton
  icon={SvgStar}
  state={isFavorite ? "selected" : "empty"}
  onClick={toggleFavorite}
>
  Favorite
</SelectButton>

// Foldable — icon stays visible, label folds away
<SelectButton
  foldable
  icon={SvgStar}
  state="empty"
>
  Favorite
</SelectButton>
```
