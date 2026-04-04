# Card

**Import:** `import { Card } from "@opal/layouts";`

A namespace of card layout primitives. Each sub-component handles a specific region of a card.

## Card.Header

A card header layout that pairs a [`Content`](../content/README.md) block with a right-side column and an optional full-width children slot.

### Why Card.Header?

[`ContentAction`](../content-action/README.md) provides a single `rightChildren` slot. Card headers typically need two distinct right-side regions — a primary action on top and secondary actions on the bottom. `Card.Header` provides this with `rightChildren` and `bottomRightChildren` slots, plus a `children` slot for full-width content below the header row (e.g., search bars, expandable tool lists).

### Props

Inherits **all** props from [`Content`](../content/README.md) (icon, title, description, sizePreset, variant, editable, onTitleChange, suffix, etc.) plus:

| Prop | Type | Default | Description |
|---|---|---|---|
| `rightChildren` | `ReactNode` | `undefined` | Content rendered to the right of the Content block (top of right column). |
| `bottomRightChildren` | `ReactNode` | `undefined` | Content rendered below `rightChildren` in the same column. Laid out as `flex flex-row`. |
| `children` | `ReactNode` | `undefined` | Content rendered below the full header row, spanning the entire width. |

### Layout Structure

```
+---------------------------------------------------------+
| [Content (p-2, self-start)]    [rightChildren]          |
|  icon + title + description    [bottomRightChildren]    |
+---------------------------------------------------------+
| [children — full width]                                 |
+---------------------------------------------------------+
```

- Outer wrapper: `flex flex-col w-full`
- Header row: `flex flex-row items-stretch w-full`
- Content area: `flex-1 min-w-0 self-start p-2` — top-aligned with fixed padding
- Right column: `flex flex-col items-end shrink-0` — no padding, no gap
- `bottomRightChildren` wrapper: `flex flex-row` — lays children out horizontally
- `children` wrapper: `w-full` — only rendered when children are provided

### Usage

#### Card with primary and secondary actions

```tsx
import { Card } from "@opal/layouts";
import { Button } from "@opal/components";
import { SvgGlobe, SvgSettings, SvgUnplug, SvgCheckSquare } from "@opal/icons";

<Card.Header
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

#### Card with only a connect action

```tsx
<Card.Header
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

#### Card with expandable children

```tsx
<Card.Header
  icon={SvgServer}
  title="MCP Server"
  description="12 tools available"
  sizePreset="main-ui"
  variant="section"
  rightChildren={<Button icon={SvgSettings} prominence="tertiary" />}
>
  <SearchBar placeholder="Search tools..." />
</Card.Header>
```

#### No right children

```tsx
<Card.Header
  icon={SvgInfo}
  title="Section Header"
  description="Description text"
  sizePreset="main-content"
  variant="section"
/>
```

When both `rightChildren` and `bottomRightChildren` are omitted and no `children` are provided, the component renders only the padded `Content`.
