# Button

**Import:** `import { Button, type ButtonProps } from "@opal/components";`

A single component that handles both labeled buttons and icon-only buttons. It replaces the legacy `refresh-components/buttons/Button` and `refresh-components/buttons/IconButton` with a unified API built on `Interactive.Base` > `Interactive.Container`.

## Architecture

```
Interactive.Base          <- variant/subvariant, selected, disabled, href, onClick
  └─ Interactive.Container  <- height, rounding, padding (derived from `size`)
       └─ div.opal-button.interactive-foreground  <- flexbox row layout
            ├─ Icon?          .opal-button-icon   (1rem x 1rem, shrink-0)
            ├─ <span>?        .opal-button-label  (whitespace-nowrap, font)
            └─ RightIcon?     .opal-button-icon
```

- **Colors are not in the Button.** `Interactive.Base` sets `background-color` and `--interactive-foreground` per variant/subvariant/state. The `.interactive-foreground` utility class on the content div sets `color: var(--interactive-foreground)`, which both the `<span>` text and `stroke="currentColor"` SVG icons inherit automatically.
- **Layout is in `styles.css`.** The CSS classes (`.opal-button`, `.opal-button-icon`, `.opal-button-label`) handle flexbox alignment, gap, icon sizing, and text styling. A `[data-size="compact"]` selector tightens the gap and reduces font size.
- **Sizing is delegated to `Interactive.Container` presets.** The `size` prop maps to Container height/rounding/padding presets:
  - `"default"` -> height 2.25rem, rounding 12px, padding 8px
  - `"compact"` -> height 1.75rem, rounding 8px, padding 4px
- **Icon-only buttons render as squares** because `Interactive.Container` enforces `min-width >= height` for every height preset.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `variant` | `"default" \| "action" \| "danger" \| "none" \| "select"` | `"default"` | Top-level color variant (maps to `Interactive.Base`) |
| `subvariant` | Depends on `variant` | `"primary"` | Color subvariant -- e.g. `"primary"`, `"secondary"`, `"ghost"` for default/action/danger |
| `icon` | `IconFunctionComponent` | -- | Left icon component |
| `children` | `string` | -- | Button label text. Omit for icon-only buttons |
| `rightIcon` | `IconFunctionComponent` | -- | Right icon component |
| `size` | `SizeVariant` | `"default"` | Size preset controlling height, rounding, padding, gap, and font size |
| `tooltip` | `string` | -- | Tooltip text shown on hover |
| `tooltipSide` | `TooltipSide` | `"top"` | Which side the tooltip appears on |
| `selected` | `boolean` | `false` | Forces the selected visual state (data-selected) |
| `disabled` | `boolean` | `false` | Disables the button (data-disabled, aria-disabled) |
| `href` | `string` | -- | URL; renders an `<a>` wrapper instead of Radix Slot |
| `onClick` | `MouseEventHandler<HTMLElement>` | -- | Click handler |
| _...and all other `InteractiveBaseProps`_ | | | `group`, `static`, `ref`, etc. |

## Usage examples

```tsx
import { Button } from "@opal/components";
import { SvgPlus, SvgArrowRight } from "@opal/icons";

// Primary button with label
<Button variant="default" onClick={handleClick}>
  Save changes
</Button>

// Icon-only button (renders as a square)
<Button icon={SvgPlus} subvariant="ghost" size="compact" />

// Labeled button with left icon
<Button icon={SvgPlus} variant="action">
  Add item
</Button>

// Labeled button with right icon
<Button rightIcon={SvgArrowRight} variant="default" subvariant="secondary">
  Continue
</Button>

// Compact danger button, disabled
<Button variant="danger" size="compact" disabled>
  Delete
</Button>

// As a link
<Button href="/settings" variant="default" subvariant="ghost">
  Settings
</Button>

// Selected state (e.g. inside a popover trigger)
<Button icon={SvgFilter} subvariant="ghost" selected={isOpen} />

// With tooltip
<Button icon={SvgPlus} subvariant="ghost" tooltip="Add item" />
```

## Migration from legacy buttons

| Legacy prop | Opal equivalent |
|-------------|-----------------|
| `main` | `variant="default"` (default, can be omitted) |
| `action` | `variant="action"` |
| `danger` | `variant="danger"` |
| `primary` | `subvariant="primary"` (default, can be omitted) |
| `secondary` | `subvariant="secondary"` |
| `tertiary` | `subvariant="ghost"` |
| `transient={x}` | `selected={x}` |
| `size="md"` | `size="compact"` |
| `size="lg"` | `size="default"` (default, can be omitted) |
| `leftIcon={X}` | `icon={X}` |
| `IconButton icon={X}` | `<Button icon={X} />` (no children = icon-only) |
| `tooltip="..."` | `tooltip="..."` |
