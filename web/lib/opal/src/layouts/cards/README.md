# Card

**Import:** `import { Card } from "@opal/layouts";`

A namespace of card layout primitives. Each sub-component handles a specific region of a card.

## Card.Header

A card header layout with a main content slot and a full-width `bottomChildren` slot.

### Why Card.Header?

`Card.Header` is layout-only — it provides `children` for the main content area plus `bottomChildren` for a secondary slot. For the typical icon/title/description + right-action pattern, pass a `<ContentAction />` into `children` with `rightChildren` for the action button.

### Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `children` | `ReactNode` | `undefined` | Content rendered in the header slot — typically a `<ContentAction />` block. |
| `bottomChildren` | `ReactNode` | `undefined` | Content rendered below the entire header, spanning the full width. |

### Layout Structure

```
+-----------------------------------+
| children                          |
+-----------------------------------+
| bottomChildren (full width)       |
+-----------------------------------+
```

- Outer wrapper: `flex flex-col w-full`
- Header row: `flex flex-row items-start w-full` — columns are independent in height
- Left column (children wrapper): `self-start grow min-w-0` — grows to fill available space
- `bottomChildren` wrapper: `w-full` — only rendered when provided

### Usage

#### Card with right action

```tsx
import { Card, ContentAction } from "@opal/layouts";
import { Button } from "@opal/components";
import { SvgGlobe, SvgCheckSquare } from "@opal/icons";

<Card.Header>
  <ContentAction
    icon={SvgGlobe}
    title="Google Search"
    description="Web search provider"
    sizePreset="main-ui"
    variant="section"
    padding="fit"
    rightChildren={
      <Button icon={SvgCheckSquare} variant="action" prominence="tertiary">
        Current Default
      </Button>
    }
  />
</Card.Header>
```

#### Card with only a connect action

```tsx
<Card.Header>
  <ContentAction
    icon={SvgCloud}
    title="OpenAI"
    description="Not configured"
    sizePreset="main-ui"
    variant="section"
    padding="fit"
    rightChildren={
      <Button rightIcon={SvgArrowExchange} prominence="tertiary">
        Connect
      </Button>
    }
  />
</Card.Header>
```

#### Card with bottom children

```tsx
<Card.Header
  bottomChildren={<SearchBar placeholder="Search tools..." />}
>
  <ContentAction
    icon={SvgServer}
    title="MCP Server"
    description="12 tools available"
    sizePreset="main-ui"
    variant="section"
    padding="fit"
    rightChildren={<Button icon={SvgSettings} prominence="tertiary" />}
  />
</Card.Header>
```

#### No actions

```tsx
<Card.Header>
  <ContentAction
    icon={SvgInfo}
    title="Section Header"
    description="Description text"
    sizePreset="main-content"
    variant="section"
    padding="fit"
  />
</Card.Header>
```
