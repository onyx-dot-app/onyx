# Button

**Import:** `import { Button, type ButtonProps } from "@opal/components";`

A single component that handles both labeled buttons and icon-only buttons. Built on `Interactive.Stateless` > `Interactive.Container`.

## Architecture

```
Interactive.Stateless          <- variant, prominence, interaction, disabled, href, onClick
  └─ Interactive.Container     <- height, rounding, padding (from `size`), border (auto for secondary)
       └─ div.opal-button.interactive-foreground
            ├─ div > Icon?       (interactive-foreground-icon)
            ├─ <span>?           .opal-button-label
            └─ div > RightIcon?  (interactive-foreground-icon)
```

- **Colors are not in the Button.** `Interactive.Stateless` sets `background-color`, `--interactive-foreground`, and `--interactive-foreground-icon` per variant/prominence/state. Descendants opt in via the `.interactive-foreground` and `.interactive-foreground-icon` utility classes.
- **Icon-only buttons render as squares** because `Interactive.Container` enforces `min-width >= height`.
- **Border is automatic for `prominence="secondary"`.** The Container receives `border={prominence === "secondary"}` internally.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `variant` | `"default" \| "action" \| "danger" \| "none"` | `"default"` | Color variant |
| `prominence` | `"primary" \| "secondary" \| "tertiary" \| "internal"` | `"primary"` | Color prominence |
| `interaction` | `"rest" \| "hover" \| "active"` | `"rest"` | JS-controlled interaction override |
| `icon` | `IconFunctionComponent` | — | Left icon |
| `children` | `string` | — | Label text. Omit for icon-only buttons |
| `rightIcon` | `IconFunctionComponent` | — | Right icon |
| `responsiveHideText` | `boolean` | `false` | Hides label on small screens |
| `size` | `SizeVariant` | `"lg"` | Size preset |
| `type` | `"submit" \| "button" \| "reset"` | `"button"` | HTML button type |
| `width` | `WidthVariant` | — | Width preset |
| `tooltip` | `string` | — | Tooltip text |
| `tooltipSide` | `TooltipSide` | `"top"` | Tooltip placement |
| `disabled` | `boolean` | `false` | Disables the button |
| `href` | `string` | — | URL; renders as a link |

## Usage

```tsx
import { Button } from "@opal/components";
import { SvgPlus, SvgArrowRight } from "@opal/icons";

// Primary button with label
<Button variant="default" onClick={handleClick}>Save changes</Button>

// Icon-only button (renders as a square)
<Button icon={SvgPlus} prominence="tertiary" size="sm" />

// Secondary button (auto border)
<Button rightIcon={SvgArrowRight} prominence="secondary">Continue</Button>

// Interaction override (e.g. inside a popover trigger)
<Button icon={SvgFilter} prominence="tertiary" interaction={isOpen ? "hover" : "rest"} />
```
