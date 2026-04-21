# Card

**Import:** `import { Card } from "@opal/layouts";`

A namespace of card layout primitives. Each sub-component handles a specific region of a card.

## Card.Header

A flexible card header with one slot for the main header content, two stacked slots in a right-side column, and a full-width slot below.

### Why Card.Header?

[`ContentAction`](../content-action/README.md) provides a single right-side slot. Card headers typically need more — a primary action on top, secondary actions on the bottom, and sometimes a full-width region beneath the entire row (e.g. expandable details, search bars, secondary info).

`Card.Header` is layout-only — it intentionally doesn't bake in `Content` props. Pass a `<Content />` (or any other element) into `headerChildren` for the icon/title/description region.

### Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `headerChildren` | `ReactNode` | `undefined` | Content rendered in the top-left header slot — typically a `<Content />` block. |
| `headerPadding` | `"sm" \| "fit"` | `"fit"` | Padding applied around `headerChildren`. `"sm"` → `p-2`; `"fit"` → `p-0`. |
| `topRightChildren` | `ReactNode` | `undefined` | Content rendered to the right of `headerChildren` (top of right column). |
| `bottomRightChildren` | `ReactNode` | `undefined` | Content rendered below `topRightChildren` in the same column. Laid out as `flex flex-row`. |
| `bottomChildren` | `ReactNode` | `undefined` | Content rendered below the entire header (left + right columns), spanning the full width. |

### Layout Structure

```
+------------------+----------------+
| headerChildren   | topRight       |
+                  +----------------+
|                  | bottomRight    |
+------------------+----------------+
| bottomChildren (full width)       |
+-----------------------------------+
```

- Outer wrapper: `flex flex-col w-full`
- Header row: `flex flex-row items-start w-full` — columns are independent in height
- Left column (headerChildren wrapper): `self-start grow min-w-0` + `headerPadding` variant (default `p-0`) — grows to fill available space
- Right column: `flex flex-col items-end shrink-0` — shrinks to fit its content
- `bottomChildren` wrapper: `w-full` — only rendered when provided

### Usage

#### Card with primary and secondary actions

```tsx
import { Card, Content } from "@opal/layouts";
import { Button } from "@opal/components";
import { SvgGlobe, SvgSettings, SvgUnplug, SvgCheckSquare } from "@opal/icons";

<Card.Header
  headerChildren={
    <Content
      icon={SvgGlobe}
      title="Google Search"
      description="Web search provider"
      sizePreset="main-ui"
      variant="section"
    />
  }
  topRightChildren={
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
  headerChildren={
    <Content
      icon={SvgCloud}
      title="OpenAI"
      description="Not configured"
      sizePreset="main-ui"
      variant="section"
    />
  }
  topRightChildren={
    <Button rightIcon={SvgArrowExchange} prominence="tertiary">
      Connect
    </Button>
  }
/>
```

#### Card with extra info beneath the header

```tsx
<Card.Header
  headerChildren={
    <Content
      icon={SvgServer}
      title="MCP Server"
      description="12 tools available"
      sizePreset="main-ui"
      variant="section"
    />
  }
  topRightChildren={<Button icon={SvgSettings} prominence="tertiary" />}
  bottomChildren={<SearchBar placeholder="Search tools..." />}
/>
```

#### No slots

```tsx
<Card.Header
  headerChildren={
    <Content
      icon={SvgInfo}
      title="Section Header"
      description="Description text"
      sizePreset="main-content"
      variant="section"
    />
  }
/>
```
