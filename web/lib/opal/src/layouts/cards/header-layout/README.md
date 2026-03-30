# CardHeaderLayout

**Import:** `import { CardHeaderLayout, type CardHeaderLayoutProps } from "@opal/layouts";`

A card header layout that pairs a [`Content`](../../content/README.md) block with a right-side column of vertically stacked children.

## Why CardHeaderLayout?

[`ContentAction`](../../content-action/README.md) provides a single `rightChildren` slot. Card headers typically need two distinct right-side regions — a primary action on top and secondary actions on the bottom. `CardHeaderLayout` provides this with `rightChildren` and `bottomRightChildren` slots, with no padding or gap between them so the caller has full control over spacing.

## Props

Inherits **all** props from [`Content`](../../content/README.md) (icon, title, description, sizePreset, variant, etc.) plus:

| Prop | Type | Default | Description |
|---|---|---|---|
| `rightChildren` | `ReactNode` | `undefined` | Content rendered to the right of the Content block (top of right column). |
| `bottomRightChildren` | `ReactNode` | `undefined` | Content rendered below `rightChildren` in the same column. Laid out as `flex flex-row`. |

## Layout Structure

```
┌──────────────────────────────────────────────────────┐
│ [Content (p-2, self-start)]  [rightChildren]         │
│  icon + title + description  [bottomRightChildren]   │
└──────────────────────────────────────────────────────┘
```

- Outer wrapper: `flex flex-row items-stretch w-full`
- Content area: `flex-1 min-w-0 self-start p-2` — top-aligned with fixed padding
- Right column: `flex flex-col items-end justify-between shrink-0` — no padding, no gap
- `bottomRightChildren` wrapper: `flex flex-row` — lays children out horizontally

The right column uses `justify-between` so when both slots are present, `rightChildren` sits at the top and `bottomRightChildren` at the bottom.

## Usage

### Card with primary and secondary actions

```tsx
import { CardHeaderLayout } from "@opal/layouts";
import { Button } from "@opal/components";
import { SvgGlobe, SvgSettings, SvgUnplug, SvgCheckSquare } from "@opal/icons";

<CardHeaderLayout
  icon={SvgGlobe}
  title="Google Search"
  description="Web search provider"
  sizePreset="main-ui"
  variant="section"
  rightChildren={
    <Button icon={SvgCheckSquare} variant="action" prominence="tertiary">
      Current Default
    </Button>
  }
  bottomRightChildren={
    <>
      <Button icon={SvgUnplug} size="sm" prominence="tertiary" tooltip="Disconnect" />
      <Button icon={SvgSettings} size="sm" prominence="tertiary" tooltip="Edit" />
    </>
  }
/>
```

### Card with only a connect action

```tsx
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
```

### No right children

```tsx
<CardHeaderLayout
  icon={SvgInfo}
  title="Section Header"
  description="Description text"
  sizePreset="main-content"
  variant="section"
/>
```

When both `rightChildren` and `bottomRightChildren` are omitted, the component renders only the padded `Content`.
