# TextButton

**Import:** `import { TextButton, type TextButtonProps } from "@opal/components";`

A clickable [`Text`](../../text/README.md): the same variant/prominence hover-and-active
color animation as [`Button`](../button/README.md), but with **no background, border,
padding, or rounding**. Use it wherever a `Button` would be too heavy visually — inline
text actions, quiet toolbar actions, footer links styled as actions — and
[`LinkButton`](../link-button/README.md) is too narrow (no variant/prominence matrix, no
icon support, always underlined).

## Architecture

```
Interactive.Stateless              <- variant, prominence, interaction, disabled, href, onClick
  └─ TextButtonSurface             <- <Link> / <button> / <span>, no height/rounding/padding/border
       └─ .opal-text-button.interactive-foreground
            ├─ Icon?                 (interactive-foreground-icon)
            ├─ <Text color="inherit">?
            └─ RightIcon?            (interactive-foreground-icon)
```

- **Colors are not in `TextButton`.** Same as `Button`: `Interactive.Stateless` sets
  `--interactive-foreground` and `--interactive-foreground-icon` per variant/prominence/state.
  `TextButton` opts into text color via `.interactive-foreground`; icons opt in via
  `iconWrapper`'s `.interactive-foreground-icon`.
- **`Interactive.Stateless` also sets a `background-color`** per variant/prominence (that's
  what `Interactive.Container` normally displays). `TextButton` force-clears it
  (`background-color: transparent !important` in `styles.css`) since it never renders a
  `Container` — only the foreground color transition survives.
- **`TextButtonSurface`** is a trimmed-down copy of `Interactive.Container`'s `<Link>` /
  `<button>` / `<span>` element selection, without the height/rounding/padding/border logic
  that `Container` adds for traditional buttons.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `variant` | `"default" \| "action" \| "danger" \| "none"` | `"default"` | Color variant |
| `prominence` | `"primary" \| "secondary" \| "tertiary" \| "internal"` | `"tertiary"` | Color prominence. Defaults to `"tertiary"` (unlike `Button`'s `"primary"`) — `"primary"`'s white-on-color foreground assumes a colored surface `TextButton` doesn't provide. |
| `interaction` | `"rest" \| "hover" \| "active"` | `"rest"` | JS-controlled interaction override |
| `icon` | `IconFunctionComponent` | — | Left icon |
| `children` | `string \| RichStr` | — | Label text. Omit for icon-only |
| `rightIcon` | `IconFunctionComponent` | — | Right icon |
| `size` | `"lg" \| "md" \| "sm" \| "xs" \| "2xs" \| "fit"` | `"lg"` | Controls label/icon size (`"lg"` uses `main-ui-body`, everything else `secondary-body`) |
| `type` | `"submit" \| "button" \| "reset"` | `"button"` | HTML button type |
| `tooltip` | `string` | — | Tooltip text |
| `tooltipSide` | `TooltipSide` | `"top"` | Tooltip placement |
| `disabled` | `boolean` | `false` | Disables the button |
| `href` | `string` | — | URL; renders as a link |

## Usage

```tsx
import { TextButton } from "@opal/components";
import { SvgPlus, SvgArrowRight } from "@opal/icons";

// Bare text action — no background, just a color shift on hover
<TextButton onClick={handleClick}>Dismiss</TextButton>

// With an icon
<TextButton icon={SvgPlus} onClick={handleAdd}>Add item</TextButton>

// As a link
<TextButton href="/admin/settings" rightIcon={SvgArrowRight}>
  Go to settings
</TextButton>

// Danger variant, disabled
<TextButton variant="danger" disabled onClick={handleDelete}>
  Delete account
</TextButton>
```

## When to use `Text`, `LinkButton`, `TextButton`, or `Button`

- **`Text`** — not interactive at all; plain styled text.
- **`LinkButton`** — inline references inside prose ("Learn more", "Docs"). Always
  underlined, no variant/prominence matrix, no icon support beyond a fixed trailing
  external-link glyph.
- **`TextButton`** — a real action (click handler or navigation) that should read as
  text, not a button — full variant/prominence color matrix and icon slots, no
  underline, no background.
- **`Button`** — a traditional button surface with background, border, padding, and
  rounding.
