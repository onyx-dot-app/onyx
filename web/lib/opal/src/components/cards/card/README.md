# Card

**Import:** `import { Card, type CardProps } from "@opal/components";`

A container component with configurable background, border, padding, and rounding. Has two mutually-exclusive modes:

- **Plain** (default) — renders children inside a single styled `<div>`.
- **Expandable** (`expandable: true`) — renders children as an always-visible header plus an `expandedContent` prop that animates open/closed.

## Plain mode

Default behavior — a plain container.

```tsx
import { Card } from "@opal/components";

<Card padding={4} border="solid">
  <p>Hello</p>
</Card>
```

### Plain mode props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `padding` | `Spacing` | `4` | Padding, as a spacing step (`N / 4` rem) |
| `rounding` | `RoundingVariants` | `"md"` | Border-radius preset |
| `background` | `"none" \| "light" \| "heavy"` | `"light"` | Background fill intensity |
| `border` | `"none" \| "dashed" \| "solid"` | `"none"` | Border style |
| `borderColor` | `StatusVariants` | `"default"` | Status-palette border color (needs `border` ≠ `"none"`) |
| `disabled` | `boolean` | `false` | Dims the card and shows a not-allowed cursor. Visual only — see below. |
| `ref` | `React.Ref<HTMLDivElement>` | — | Ref forwarded to the root div |
| `children` | `React.ReactNode` | — | Card content |
| `data-*` | `string \| boolean` | — | Forwarded to the root. See below. |

### `disabled`

`disabled` dims the card and gives it a not-allowed cursor. It is **visual only** —
children stay interactive, because a card is a container and suppressing what it
holds is a stronger claim than dimming it:

```tsx
<Card disabled>…</Card>
```

Compose `Disabled` from `@opal/core` when clicks should be blocked as well, or
when you want a tooltip explaining why:

```tsx
<Disabled disabled tooltip="Connect the app first">
  <Card disabled>…</Card>
</Disabled>
```

It is a boolean rather than a variant value, so it stacks with `background` and
`border` instead of replacing them — a disabled card can still be transparent
with a dashed border.

In expandable mode the whole card dims, header and expanded body together.

### `data-*` attributes

Any `data-*` prop is forwarded to the card's root element, so an application can
label a card for tests or analytics:

```tsx
<Card data-card>…</Card>
```

A card owns how it looks, not what the surrounding app calls it — `data-*` is the
app's namespace, and silently dropping it is worse than either forwarding or
rejecting it. Only `data-*` is picked up. `className` and `style` stay out, so the
card's appearance is still its own; behavioural props such as `onClick` are a
deliberate API decision rather than something inherited by a rest spread (use
`SelectCard` for an interactive card).

The card's own `data-background`, `data-border`, `data-shadow`, and
`data-opal-status-border` are written after the forwarded attributes, so a caller
cannot repurpose them to drive the stylesheet.

### Padding scale

`padding` is a spacing step, not a preset: `N` is `N / 4` rem, the same scale Tailwind
uses. So `padding={2}` is the same distance as `p-2`, and the default `4` is `1rem`.

### Rounding scale

| `rounding` | Class        |
|------------|--------------|
| `"xs"`     | `rounded-04` |
| `"sm"`     | `rounded-08` |
| `"md"`     | `rounded-12` |
| `"lg"`     | `rounded-16` |

## Expandable mode

Enabled by passing `expandable: true`. The type is a discriminated union — `expanded` and `expandedContent` are only available (and type-checked) when `expandable: true`.

```tsx
import { Card } from "@opal/components";
import { useState } from "react";

function ProviderCard() {
  const [open, setOpen] = useState(false);

  return (
    <Card
      expandable
      expanded={open}
      expandedContent={<ModelList />}
      border="solid"
      rounding="lg"
    >
      {/* always visible — the header region */}
      <div
        onClick={() => setOpen((v) => !v)}
        className="flex items-center justify-between cursor-pointer"
      >
        <ProviderInfo />
        <SvgChevronDown
          className={cn("transition-transform", open && "rotate-180")}
        />
      </div>
    </Card>
  );
}
```

### Expandable mode props

Everything from plain mode, **plus**:

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `expandable` | `true` | — | Required to enable the expandable variant |
| `expanded` | `boolean` | `false` | Controlled expanded state. Card never mutates this. |
| `expandedContent` | `React.ReactNode` | — | The body that animates open/closed below the header |

### Behavior

- **No trigger baked in.** Card does not attach any click handlers. Callers wire their own `onClick` / keyboard / button / etc. to toggle state. This keeps `padding` semantics consistent across modes and avoids surprises with interactive children.
- **Always controlled.** `expanded` is a pure one-way visual prop. There is no `defaultExpanded` or `onExpandChange` — the caller owns state entirely (`useState` at the call site).
- **No React context.** The component renders a flat tree; there are no compound sub-components (`Card.Header` / `Card.Content`) and no exported context hooks.
- **Rounding adapts automatically.** When `expanded && expandedContent !== undefined`, the header's bottom corners flatten and the content's top corners flatten so they meet seamlessly. When collapsed (or when `expandedContent` is undefined), the header is fully rounded.
- **Content background is always transparent.** The `background` prop applies to the header only; the content slot never fills its own background so the page shows through and keeps the two regions visually distinct.
- **Content has no intrinsic padding.** The `padding` prop applies to the header only. Callers own any padding inside whatever they pass to `expandedContent` — wrap it in a `<div className="p-4">` (or whatever) if you want spacing.
- **Animation.** Content uses a pure CSS grid `0fr ↔ 1fr` animation with an opacity fade (~200ms ease-out). No `@radix-ui/react-collapsible` dependency.

### Accessibility

Because Card doesn't own the trigger, it also doesn't generate IDs or ARIA attributes. Consumers are responsible for wiring `aria-expanded`, `aria-controls`, `aria-labelledby`, etc. on their trigger element.

## Complete prop reference

```ts
type CardBaseProps = {
  padding?: Spacing;
  rounding?: RoundingVariants;
  background?: "none" | "light" | "heavy";
  border?: "none" | "dashed" | "solid";
  borderColor?: StatusVariants;
  ref?: React.Ref<HTMLDivElement>;
  children?: React.ReactNode;
};

type CardPlainProps = CardBaseProps & { expandable?: false };

type CardExpandableProps = CardBaseProps & {
  expandable: true;
  expanded?: boolean;
  expandedContent?: React.ReactNode;
};

type CardProps = CardPlainProps | CardExpandableProps;
```

The discriminated union enforces:

```tsx
<Card expanded>…</Card>                   // ❌ TS error — `expanded` not in plain mode
<Card expandable expandedContent={…}>…</Card>     // ✅ expandable mode
<Card border="solid">…</Card>             // ✅ plain mode
```
