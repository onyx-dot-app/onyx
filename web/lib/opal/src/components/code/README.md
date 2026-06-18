# Code

A block code snippet with an optional hover-reveal copy button.

Uses `Hoverable.Root` / `Hoverable.Item` so the copy button appears on hover without any manual CSS — fully consistent with Opal hover patterns.

## Usage

```tsx
import { Code } from "@opal/components";

// With copy button (default)
<Code>npm install @onyx/sdk</Code>

// Without copy button
<Code showCopyButton={false}>{"const x = 1;"}</Code>
```

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `children` | `string` | — | **Required.** The code text to display. |
| `showCopyButton` | `boolean` | `true` | Show the hover-reveal copy-to-clipboard button. |

All other `HTMLElement` attributes (except `style` and `className`) are forwarded to the inner `<code>` element.

## Notes

- Font: `font-secondary-mono` (12px DM Mono, consistent with the Opal design system).
- Background and border follow the `background-tint-00` / `border-01` tokens.
- Long lines wrap with `break-all` to prevent horizontal overflow.
- The copy button is absolutely positioned at the top-right and fades in on hover via `Hoverable.Item variant="appear-on-hover"`.
