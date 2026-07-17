# TextButton

**Import:** `import { TextButton, type TextButtonProps } from "@opal/components";`

A clickable [`Text`](../../text/README.md): the same hover/active color animation as
[`Button`](../button/README.md), driven by `Interactive.Stateless`, but with **no
background, border, padding, or rounding**. Props are shaped like `Text` (`font`,
`nowrap`, required `children`), not `Button` — there's no `icon`/`rightIcon`,
`variant`, `prominence`, `tooltip`, or `size`. Use it wherever a `Button` would be too
heavy visually — inline text actions, quiet toolbar actions — and
[`LinkButton`](../link-button/README.md) is too narrow (always underlined, no icon
slots).

## Architecture

```
Interactive.Stateless              <- always variant="default" / prominence="tertiary"; disabled, href, onClick
  └─ <Link> / <button>             <- .opal-text-button.interactive-foreground, no height/rounding/padding/border
       └─ <Text font={font} color="inherit">
```

- **No separate surface component.** `Button` needs `Interactive.Container` because it
  has to *discover* `href`/`disabled`/etc. from Radix `Slot`-injected props (it's a
  generic primitive reused by many callers). `TextButton` already has `href`/`target`/
  `disabled` in scope as its own props, so it renders `<Link>`/`<button>` directly as
  `Interactive.Stateless`'s single child. Radix `Slot` auto-merges `className` (joins
  both), `style` (merges objects), and event handlers (chains them) onto that element —
  everything else falls through untouched — so no manual prop-merging is needed.
- **Colors are not in `TextButton`.** Same as `Button`: `Interactive.Stateless` sets
  `--interactive-foreground` per state. `TextButton` opts into it via
  `.interactive-foreground`, and the label reads it via `Text`'s `color="inherit"`.
- **`variant`/`prominence` are always `"default"`/`"tertiary"`** internally and aren't
  exposed — `TextButton` never has a `Container` to paint a background onto, so the
  color-family and prominence tiers `Button` offers don't apply. `TextButton` is a
  single, fixed subtle color animation (`text-03` → `text-04` on hover → `text-05` on
  active), same as `Button`'s default+tertiary combination.
- **`Interactive.Stateless` still paints a background-color** for `prominence="tertiary"`
  on hover/active (that's normally shown by `Interactive.Container`). `TextButton`
  force-clears it in `styles.css` (`background-color: transparent !important`) since it
  never renders a `Container` — only the foreground color transition survives.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `font` | `TextFont` | `"main-ui-body"` | Font preset, same as `Text`'s `font` prop |
| `nowrap` | `boolean` | `true` | Prevent text wrapping (defaults `true`, unlike `Text`, since buttons don't usually wrap) |
| `children` | `string \| RichStr` | — | Label text (required) |
| `href` | `string` | — | URL; renders as a link |
| `target` | `string` | — | Anchor target (e.g. `"_blank"`). Only meaningful with `href` |
| `disabled` | `boolean` | `false` | Applies disabled styling + suppresses clicks/navigation |

## Usage

```tsx
import { TextButton } from "@opal/components";

// Bare text action — no background, just a color shift on hover
<TextButton onClick={handleClick}>Dismiss</TextButton>

// As a link
<TextButton href="/admin/settings">Go to settings</TextButton>

// Disabled
<TextButton disabled onClick={handleDelete}>
  Delete account
</TextButton>

// Custom font preset
<TextButton font="secondary-action" onClick={handleClick}>
  Undo
</TextButton>
```

## When to use `Text`, `LinkButton`, `TextButton`, or `Button`

- **`Text`** — not interactive at all; plain styled text.
- **`LinkButton`** — inline references inside prose ("Learn more", "Docs"). Always
  underlined.
- **`TextButton`** — a real action (click handler or navigation) that should read as
  text, not a button — no underline, no background.
- **`Button`** — a traditional button surface with background, border, padding,
  rounding, icon slots, and a variant/prominence color matrix.
