# SelectCard

**Import:** `import { SelectCard, type SelectCardProps } from "@opal/components";`

A stateful interactive card — the card counterpart to [`SelectButton`](../../buttons/select-button/README.md). Built on `Interactive.Stateful` (Slot) with a structural `<div>` that owns padding, rounding, border, and overflow. Always uses the `select-card` Interactive.Stateful variant internally.

Two mutually-exclusive modes:

- **Plain** (default) — one interactive card.
- **Expandable** (`expandable: true`) — `children` become the interactive header and `expandedContent` an animating body below it.

## Relationship to Card

`Card` is a plain, non-interactive container. `SelectCard` adds stateful interactivity (hover, active, disabled, state-driven colors) by wrapping its root div with `Interactive.Stateful`. Both share the same independent `padding` / `rounding` API.

## Relationship to SelectButton

SelectCard and SelectButton share the same call stack:

```
Interactive.Stateful → structural element → content
```

The key differences:

- SelectCard renders a `<div>` (not `Interactive.Container`) — cards have their own rounding scale and don't need Container's height/min-width.
- SelectCard has no `foldable` prop — use `Interactive.Foldable` directly inside children. That is hover-reveal, and unrelated to `expandable` below.
- SelectCard's children are fully composable — use `CardHeaderLayout`, `ContentAction`, `Content`, buttons, etc. inside.

## Keyboard

The root is a `<div>` so children can be buttons and links, which HTML forbids inside a `<button>`. A card with `onClick` joins the tab order and fires `onClick` on Enter or Space. While keyboard-focused it paints exactly like hover, so pointer and keyboard users see the same affordance. Keys pressed on a nested control never reach the card. A nested button that only repeats the card's action can leave the tab order with `tabIndex={-1}`.

The card takes no ARIA role of its own. A role such as `button` would fold every nested button into the card's accessible name, which is wrong for cards that host their own actions. A card that is one action can pass `role` and `aria-label` itself; a caller's `tabIndex` also wins over the default.

## Architecture

```
Interactive.Stateful (variant="select-card")  <- state, interaction, disabled, onClick
  └─ div.opal-select-card                    <- padding, rounding, border, overflow
       └─ children (composable)
```

The `Interactive.Stateful` Slot merges onto the div, producing a single DOM element with both `.opal-select-card` and `.interactive` classes plus `data-interactive-*` attributes. This activates the Stateful color matrix for backgrounds and `--interactive-foreground` / `--interactive-foreground-icon` CSS properties for descendants.

## Props

Inherits **all** props from `InteractiveStatefulProps` (except `variant`, which is hardcoded to `select-card`) plus:

| Prop       | Type                        | Default   | Description                                        |
| ---------- | --------------------------- | --------- | -------------------------------------------------- |
| `padding`  | `Spacing`                   | `4`       | Padding, as a spacing step (`N / 4` rem)           |
| `rounding` | `Rounding`                  | `3`       | Corner radius step (`N / 4` rem, or `"full"`)      |
| `border`   | `BorderVariants`            | `"solid"` | Border style (`"none"` \| `"dashed"` \| `"solid"`) |
| `ref`      | `React.Ref<HTMLDivElement>` | —         | Ref forwarded to the root div                      |
| `children` | `React.ReactNode`           | —         | Card content, or the header in expandable mode     |

### Expandable mode props

Everything above, **plus**:

| Prop                      | Type                | Default | Description                                                    |
| ------------------------- | ------------------- | ------- | -------------------------------------------------------------- |
| `expandable`              | `true`              | —       | Required to enable the expandable variant                      |
| `expanded`                | `boolean`           | `false` | Controlled expanded state. SelectCard never mutates this.      |
| `expandedContent`         | `React.ReactNode`   | —       | The body that animates open and closed below the header        |
| `expandableContentHeight` | `80 \| "full"`      | `80`    | `80` caps the body at 20rem with scroll; `"full"` does not cap  |

### Expandable behaviour

- **Only the header is interactive.** `Interactive.Stateful` wraps the header alone, so `onClick`, hover and the state colours stay there. A form inside `expandedContent` keeps its own clicks instead of toggling the card.
- **Always controlled.** `expanded` is a one-way visual prop. There is no `defaultExpanded` and no `onExpandChange` — the caller owns the state and the trigger, exactly as with [`Card`](../card/README.md).
- **Rounding adapts.** Expanded, the header rounds only at the top and the fold only at the bottom, so they read as one card. The corners animate over 200ms.
- **The separator keeps its resting colour.** The header's bottom border stays `border-01` while expanded, even on a selected card, so it reads as a divider rather than an edge.
- **`padding` applies to the header only.** The fold has no intrinsic padding; pad whatever you pass to `expandedContent`.
- **The fold is shared with `Card`.** Both render `CardFold` from `cards/fold/`, a grid `0fr ↔ 1fr` animation with an opacity fade. No Radix, and the children are never unmounted.

```tsx
const [open, setOpen] = useState(false);

<SelectCard
  expandable
  expanded={open}
  state={open ? "selected" : "empty"}
  onClick={() => setOpen((value) => !value)}
  expandedContent={<div className="p-4">…</div>}
>
  <ContentAction icon={SvgPlusCircle} title="New account" />
</SelectCard>;
```

### Padding scale

`padding` is a spacing step, not a preset: `N` is `N / 4` rem, the same scale Tailwind
uses. So `padding={2}` is the same distance as `p-2`, and the default `4` is `1rem`.

### Rounding scale

`Rounding` is on the same scale as `Spacing`: `N` is `N / 4` rem, so
`rounding={2}` is the same distance as `padding={2}`.

| `rounding` | rem     | px   |
| ---------- | ------- | ---- |
| `0.5`      | `0.125` | 2    |
| `1`        | `0.25`  | 4    |
| `2`        | `0.5`   | 8    |
| `3`        | `0.75`  | 12   |
| `4`        | `1`     | 16   |
| `5`        | `1.25`  | 20   |
| `"full"`   | —       | pill |

### State colors (`select-card` variant)

| State      | Rest background       | Rest foreground            |
| ---------- | --------------------- | -------------------------- |
| `empty`    | transparent           | `text-04` / icon `text-03` |
| `filled`   | `background-tint-00`  | `text-04` / icon `text-03` |
| `selected` | `action-selection-01` | `action-selection-05`      |

## CSS

SelectCard's stylesheet (`styles.css`) provides:

- `w-full overflow-clip` base styles
- Border style via `data-border` (`none` / `dashed` / `solid`)
- Border color tied to state: `border-01` for `empty`/`filled`, `var(--interactive-foreground)` for `selected`

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
    rightChildren={
      <Button icon={SvgCheckSquare} variant="action" prominence="tertiary">
        Current Default
      </Button>
    }
    bottomRightChildren={
      <Button icon={SvgSettings} size="sm" prominence="tertiary" />
    }
  />
</SelectCard>;
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
    rightChildren={
      <Button rightIcon={SvgArrowExchange} prominence="tertiary">
        Connect
      </Button>
    }
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
