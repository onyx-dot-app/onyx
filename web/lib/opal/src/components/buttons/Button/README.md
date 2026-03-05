# Button

**Import:** `import { Button, type ButtonProps } from "@opal/components";`

A single component that handles both labeled buttons and icon-only buttons. Built on `Interactive.Base` > `Interactive.Container`.

## Architecture

```
Interactive.Base            <- variant/prominence, transient, disabled, href, onClick, ref
  └─ Interactive.Container  <- height, rounding, padding (derived from `size`), border (auto for secondary)
       └─ div.opal-button.interactive-foreground  <- flexbox row layout
            ├─ div > Icon?         (lg/md/sm/fit: 1rem, xs/2xs: 0.75rem, shrink-0)
            ├─ <span>?             .opal-button-label  (lg: font-main-ui-body, other: font-secondary-body)
            └─ div > RightIcon?    (same sizing as Icon)
```

- **Colors are not in the Button.** `Interactive.Base` sets `background-color` and `--interactive-foreground` per variant/prominence/state. The `.interactive-foreground` utility class on the content div sets `color: var(--interactive-foreground)`, which both the `<span>` text and `stroke="currentColor"` SVG icons inherit automatically.
- **Icon-only buttons render as squares** because `Interactive.Container` enforces `min-width >= height` for every height preset.
- **Border is automatic for `prominence="secondary"`.** The Container receives `border={prominence === "secondary"}` internally.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `variant` | `"default" \| "action" \| "danger" \| "none" \| "select" \| "sidebar"` | `"default"` | Color variant (maps to `Interactive.Base`) |
| `prominence` | Depends on `variant` | `"primary"` | Color prominence. `"secondary"` automatically renders a border. |
| `icon` | `IconFunctionComponent` | — | Left icon component |
| `children` | `string` | — | Button label text. Omit for icon-only buttons |
| `rightIcon` | `IconFunctionComponent` | — | Right icon component |
| `size` | `SizeVariant` | `"lg"` | Size preset: `"lg"`, `"md"`, `"sm"`, `"xs"`, `"2xs"`, `"fit"` |
| `type` | `"submit" \| "button" \| "reset"` | `"button"` | HTML button type |
| `width` | `WidthVariant` | `"auto"` | Width preset. `"auto"` shrink-wraps, `"full"` stretches. |
| `foldable` | `boolean` | `false` | When `true`, `icon` and `children` are required; label + rightIcon fold away responsively |
| `responsiveHideText` | `boolean` | `false` | Hides the label below `md` breakpoint (icon-only branch) |
| `tooltip` | `string` | — | Tooltip text shown on hover |
| `tooltipSide` | `TooltipSide` | `"top"` | Which side the tooltip appears on |
| `selected` | `boolean` | `false` | Selected state (available with `variant="select"` or `"sidebar"`) |
| `transient` | `boolean` | `false` | Forces the transient (hover) visual state |
| `disabled` | `boolean` | `false` | Disables the button |
| `href` | `string` | — | URL; renders an `<a>` wrapper |
| `onClick` | `MouseEventHandler<HTMLElement>` | — | Click handler |
| `ref` | `React.Ref<HTMLElement>` | — | Ref forwarded to the underlying element via `Interactive.Base` |
| _...and all other `InteractiveBaseProps`_ | | | `group`, `target`, etc. |

## Usage examples

```tsx
import { Button } from "@opal/components";
import { SvgPlus, SvgArrowRight } from "@opal/icons";

// Primary button with label
<Button onClick={handleClick}>Save changes</Button>

// Icon-only button (renders as a square)
<Button icon={SvgPlus} prominence="tertiary" size="sm" />

// Labeled button with left icon
<Button icon={SvgPlus} variant="action">Add item</Button>

// Secondary button (automatically renders a border)
<Button rightIcon={SvgArrowRight} prominence="secondary">Continue</Button>

// Danger button, disabled
<Button variant="danger" size="md" disabled>Delete</Button>

// As a link
<Button href="/settings" prominence="tertiary">Settings</Button>

// Full-width submit button
<Button type="submit" width="full">Save</Button>

// With tooltip
<Button icon={SvgPlus} prominence="tertiary" tooltip="Add item" />
```
