# SelectCard

**Import:** `import { SelectCard, type SelectCardProps } from "@opal/components";`

A stateful interactive card — the card counterpart to [`SelectButton`](../../buttons/select-button/README.md). Built on `Interactive.Stateful` (Slot) with a structural `<div>` that owns padding, rounding, border, and overflow. Always uses the `select-card` Interactive.Stateful variant internally.

## Relationship to Card

`Card` is a plain, non-interactive container. `SelectCard` adds stateful interactivity (hover, active, disabled, state-driven colors) by wrapping its root div with `Interactive.Stateful`. Both share the same independent `padding` / `rounding` API.

## Relationship to SelectButton

SelectCard and SelectButton share the same call stack:

```
Interactive.Stateful → structural element → content
```

The key differences:

- SelectCard renders a `<div>` (not `Interactive.Container`) — cards have their own rounding scale and don't need Container's height/min-width.
- SelectCard has no `foldable` prop — use `Interactive.Foldable` directly inside children.
- SelectCard's children are fully composable — use `CardHeaderLayout`, `ContentAction`, `Content`, buttons, etc. inside.

## Architecture

```
Interactive.Stateful (variant="select-card")  <- state, interaction, disabled, onClick
  └─ div.opal-select-card                    <- padding, rounding, border, overflow
       └─ children (composable)
```

The `Interactive.Stateful` Slot merges onto the div, producing a single DOM element with both `.opal-select-card` and `.interactive` classes plus `data-interactive-*` attributes. This activates the Stateful color matrix for backgrounds and `--interactive-foreground` / `--interactive-foreground-icon` CSS properties for descendants.

## Props

Inherits **all** props from `InteractiveStatefulProps` (except `variant`, which is hardcoded to `select-card`) plus:

| Prop | Type | Default | Description |
|---|---|---|---|
| `padding` | `PaddingVariants` | `"sm"` | Padding preset |
| `rounding` | `RoundingVariants` | `"lg"` | Border-radius preset |
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

### State colors (`select-card` variant)

| State | Rest background | Rest foreground |
|---|---|---|
| `empty` | transparent | `text-04` / icon `text-03` |
| `filled` | `background-tint-00` | `text-04` / icon `text-03` |
| `selected` | `action-link-01` | `action-link-05` |

The selected state also gets a `border-action-link-05` via SelectCard's CSS.

## CSS

SelectCard's stylesheet (`styles.css`) provides:

- `w-full overflow-clip border` on all states
- `border-action-link-05` when `data-interactive-state="selected"`

All background and foreground colors come from the Interactive.Stateful CSS, not from SelectCard.

## Usage

### Provider selection card

```tsx
import { SelectCard } from "@opal/components";
import { CardHeaderLayout } from "@opal/layouts";

<SelectCard state="selected" onClick={handleClick}>
  <CardHeaderLayout
    icon={SvgGlobe}
    title="Google"
    description="Search engine"
    sizePreset="main-ui"
    variant="section"
    rightChildren={<Button icon={SvgCheckSquare} variant="action" prominence="tertiary">Current Default</Button>}
    bottomRightChildren={
      <Button icon={SvgSettings} size="sm" prominence="tertiary" />
    }
  />
</SelectCard>
```

### Disconnected state (clickable)

```tsx
<SelectCard state="empty" onClick={handleConnect}>
  <CardHeaderLayout
    icon={SvgCloud}
    title="OpenAI"
    description="Not configured"
    sizePreset="main-ui"
    variant="section"
    rightChildren={<Button rightIcon={SvgArrowExchange} prominence="tertiary">Connect</Button>}
  />
</SelectCard>
```

### With foldable hover-reveal

```tsx
<SelectCard state="filled">
  <CardHeaderLayout
    icon={SvgCloud}
    title="OpenAI"
    description="Connected"
    sizePreset="main-ui"
    variant="section"
    rightChildren={
      <div className="interactive-foldable-host flex items-center">
        <Interactive.Foldable>
          <Button rightIcon={SvgArrowRightCircle} prominence="tertiary">
            Set as Default
          </Button>
        </Interactive.Foldable>
      </div>
    }
  />
</SelectCard>
```
