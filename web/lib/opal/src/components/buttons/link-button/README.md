# LinkButton

**Import:** `import { LinkButton, type LinkButtonProps } from "@opal/components";`

A compact, anchor-styled link with an underlined label and a trailing external-link glyph. Intended for **inline references** — "Pricing", "Docs", "Learn more" — not for interactive surfaces that need hover backgrounds or prominence tiers. Use [`Button`](../button/README.md) for those.

## Architecture

Deliberately **does not** use `Interactive.Stateless` / `Interactive.Container`. Those primitives come with height, rounding, padding, and a colour matrix designed for clickable surfaces — all wrong for an inline text link.

The component renders a plain `<a>` (when given `href`) or `<button>` (when given `onClick`) with:
- `inline-flex` so the label + icon track naturally next to surrounding prose
- `text-text-03` that shifts to `text-text-05` on hover
- `underline` on the label only (the icon stays non-underlined)
- `data-disabled` driven opacity + `cursor-not-allowed` for the disabled state

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `children` | `string` | — | Visible label (required) |
| `href` | `string` | — | Destination URL. Renders the component as `<a>`. |
| `target` | `string` | — | Anchor target (e.g. `"_blank"`). Adds `rel="noopener noreferrer"` automatically when `"_blank"`. |
| `onClick` | `() => void` | — | Click handler. Without `href`, renders the component as `<button>`. |
| `disabled` | `boolean` | `false` | Applies disabled styling + suppresses navigation / clicks |
| `tooltip` | `string \| RichStr` | — | Hover tooltip text. Pass `markdown(...)` for inline markdown. |
| `tooltipSide` | `TooltipSide` | `"top"` | Tooltip placement |

Exactly one of `href` / `onClick` is expected. Passing both is allowed but only `href` takes effect (renders as an anchor).

## Usage

```tsx
import { LinkButton } from "@opal/components";

// External link — automatic rel="noopener noreferrer"
<LinkButton href="https://docs.onyx.app" target="_blank">
  Read the docs
</LinkButton>

// Internal link
<LinkButton href="/admin/settings">Settings</LinkButton>

// Button-mode (no href)
<LinkButton onClick={openModal}>Learn more</LinkButton>

// Disabled
<LinkButton href="/" disabled>
  Not available
</LinkButton>

// With a tooltip
<LinkButton
  href="/docs/pricing"
  tooltip="See plan details"
  tooltipSide="bottom"
>
  Pricing
</LinkButton>
```
