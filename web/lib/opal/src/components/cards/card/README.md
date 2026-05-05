# Card

**Import:** `import { Card, type CardProps } from "@opal/components";`

A container component with configurable background, border, padding, and rounding. Has two mutually-exclusive modes:

- **Plain** (default) — renders children inside a single styled `<div>`.
- **Expandable** (`expandable: true`) — renders children as an always-visible header plus an `expandedContent` prop that animates open/closed.

## Plain mode

Default behavior — a plain container.

```tsx
import { Card } from "@opal/components";

<Card padding="md" border="solid">
  <p>Hello</p>
</Card>
```

### Plain mode props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `padding` | `PaddingVariants` | `"md"` | Padding preset |
| `rounding` | `RoundingVariants` | `"md"` | Border-radius preset |
| `background` | `"none" \| "light" \| "heavy"` | `"light"` | Background fill intensity |
| `border` | `"none" \| "dashed" \| "solid"` | `"none"` | Border style |
| `borderColor` | `StatusVariants` | `"default"` | Status-palette border color (needs `border` ≠ `"none"`) |
| `ref` | `React.Ref<HTMLDivElement>` | — | Ref forwarded to the root div |
| `children` | `React.ReactNode` | — | Card content |

### Padding scale

| `padding` | Class   |
|-----------|---------|
| `"lg"`    | `p-6`   |
| `"md"`    | `p-4`   |
| `"sm"`    | `p-2`   |
| `"xs"`    | `p-1`   |
| `"2xs"`   | `p-0.5` |
| `"fit"`   | `p-0`   |

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
  padding?: PaddingVariants;
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
