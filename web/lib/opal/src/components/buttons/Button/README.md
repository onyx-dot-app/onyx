# Button

**Import:** `import { Button, type ButtonProps } from "@opal/components";`

A single component that handles both labeled buttons and icon-only buttons. It replaces the legacy `refresh-components/buttons/Button` and `refresh-components/buttons/IconButton` with a unified API built on `Interactive.Base` > `Interactive.Container`.

## Architecture

```
Interactive.Base            <- variant/prominence, transient, disabled, href, onClick
  └─ Interactive.Container  <- height, rounding, padding (derived from `size`), border (auto for secondary)
       └─ div.opal-button.interactive-foreground  <- flexbox row layout
            ├─ div.p-0.5 > Icon?      (compact: 12px, default: 16px, shrink-0)
            ├─ <span>?                 .opal-button-label  (whitespace-nowrap, font)
            └─ div.p-0.5 > RightIcon?  (compact: 12px, default: 16px, shrink-0)
```

- **Colors are not in the Button.** `Interactive.Base` sets `background-color` and `--interactive-foreground` per variant/prominence/state. The `.interactive-foreground` utility class on the content div sets `color: var(--interactive-foreground)`, which both the `<span>` text and `stroke="currentColor"` SVG icons inherit automatically.
- **Layout is in `styles.css`.** The CSS classes (`.opal-button`, `.opal-button-label`) handle flexbox alignment, gap, and text styling. Default labels use `font-main-ui-action` (14px/600); compact labels use `font-secondary-action` (12px/600) via a `[data-size="compact"]` selector.
- **Sizing is delegated to `Interactive.Container` presets.** The `size` prop maps to Container height/rounding/padding presets:
  - `"default"` -> height 2.25rem, rounding 12px, padding 8px
  - `"compact"` -> height 1.75rem, rounding 8px, padding 4px
- **Icon-only buttons render as squares** because `Interactive.Container` enforces `min-width >= height` for every height preset.
- **Border is automatic for `prominence="secondary"`.** The Container receives `border={prominence === "secondary"}` internally — there is no external `border` prop.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `variant` | `"default" \| "action" \| "danger" \| "none" \| "select"` | `"default"` | Top-level color variant (maps to `Interactive.Base`) |
| `prominence` | Depends on `variant` | `"primary"` | Color prominence -- e.g. `"primary"`, `"secondary"`, `"tertiary"`, `"internal"` for default/action/danger. `"secondary"` automatically renders a border. |
| `icon` | `IconFunctionComponent` | -- | Left icon component |
| `children` | `string` | -- | Button label text. Omit for icon-only buttons |
| `rightIcon` | `IconFunctionComponent` | -- | Right icon component |
| `size` | `SizeVariant` | `"default"` | Size preset controlling height, rounding, padding, icon size, and font style |
| `tooltip` | `string` | -- | Tooltip text shown on hover |
| `tooltipSide` | `TooltipSide` | `"top"` | Which side the tooltip appears on |
| `selected` | `boolean` | `false` | Switches foreground to action-link colours (only available with `variant="select"`) |
| `transient` | `boolean` | `false` | Forces the transient (hover) visual state (data-transient) |
| `disabled` | `boolean` | `false` | Disables the button (data-disabled, aria-disabled) |
| `href` | `string` | -- | URL; renders an `<a>` wrapper instead of Radix Slot |
| `onClick` | `MouseEventHandler<HTMLElement>` | -- | Click handler |
| _...and all other `InteractiveBaseProps`_ | | | `group`, `ref`, etc. |

## Usage examples

```tsx
import { Button } from "@opal/components";
import { SvgPlus, SvgArrowRight } from "@opal/icons";

// Primary button with label
<Button variant="default" onClick={handleClick}>
  Save changes
</Button>

// Icon-only button (renders as a square)
<Button icon={SvgPlus} prominence="tertiary" size="compact" />

// Labeled button with left icon
<Button icon={SvgPlus} variant="action">
  Add item
</Button>

// Secondary button (automatically renders a border)
<Button rightIcon={SvgArrowRight} variant="default" prominence="secondary">
  Continue
</Button>

// Compact danger button, disabled
<Button variant="danger" size="compact" disabled>
  Delete
</Button>

// As a link
<Button href="/settings" variant="default" prominence="tertiary">
  Settings
</Button>

// Transient state (e.g. inside a popover trigger)
<Button icon={SvgFilter} prominence="tertiary" transient={isOpen} />

// With tooltip
<Button icon={SvgPlus} prominence="tertiary" tooltip="Add item" />
```

## Migration from legacy buttons

| Legacy prop | Opal equivalent |
|-------------|-----------------|
| `main` | `variant="default"` (default, can be omitted) |
| `action` | `variant="action"` |
| `danger` | `variant="danger"` |
| `primary` | `prominence="primary"` (default, can be omitted) |
| `secondary` | `prominence="secondary"` |
| `tertiary` | `prominence="tertiary"` |
| `internal` | `prominence="internal"` |
| `transient={x}` | `transient={x}` |
| `size="md"` | `size="compact"` |
| `size="lg"` | `size="default"` (default, can be omitted) |
| `leftIcon={X}` | `icon={X}` |
| `IconButton icon={X}` | `<Button icon={X} />` (no children = icon-only) |
| `tooltip="..."` | `tooltip="..."` |
