# LineItemLayout

**Import:** `import { LineItemLayout, type LineItemLayoutProps } from "@opal/components";`

A self-contained layout component for displaying icon + title + description rows, built to match the Figma "Content Container" component from the "Text & Icon — Sizing & Pairings" spec.

## Architecture

```
div.opal-line-item-layout                   ← outer flex row (gap per variant)
  ├─ div.opal-line-item-layout-icon-container  ← fixed-size icon wrapper (centered)
  │    └─ Icon                                    (sized per variant)
  └─ div.opal-line-item-layout-content         ← flex-1 column
       ├─ div.opal-line-item-layout-content-line  ← flex row (title + right slot)
       │    ├─ span.opal-line-item-layout-title     (px-2px, min-h = line-height)
       │    └─ div.opal-line-item-layout-right      (shrink-0)
       ├─ div.opal-line-item-layout-description   ← px-2px, Secondary/Body
       └─ span.opal-line-item-layout-middle       ← optional
```

Key design decisions:
- **Flex layout** (not CSS grid) — matches the Figma component structure exactly.
- **Icon container** wraps icons with per-variant fixed dimensions, ensuring consistent alignment. The icon is centered within the container.
- **2px horizontal text padding** on all text containers — per the Figma design note: _"there is a 2px left/right padding for all texts"_.
- **rightChildren** sits inside the content line (beside the title), not at the outer flex level — this matches the Figma "Actions" placement.
- **No `Section` wrapper** — the component is self-contained; padding is the parent's concern.

## Variants

Variant names match the **Size** axis of the Figma "Content Container" component. Values sourced directly from Figma design code.

| Variant | Icon | Container | Gap | Font | Weight | Line-H | Tracking | Figma Token |
|---------|------|-----------|-----|------|--------|--------|----------|-------------|
| `headline` | 32px | 36px | 4px | 24px | 600 | 36px | -0.24px | Heading/Headline |
| `section` | 18px | 28px | 0px | 18px | 500 | 28px | -0.18px | Heading/Section Muted |
| `main-content` | 18px | 24px | 2px | 16px | 600 | 24px | — | Main Content/Emphasis |
| `main-ui` | 16px | 20px | 4px | 14px | 600 | 20px | — | Main UI/Action |
| `secondary` | 12px | 16px | 2px | 12px | 600 | 16px | — | Secondary/Action |

Description text is always Secondary/Body (12px / 400 / 16px) in `--text-03`.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `icon` | `IconFunctionComponent` | — | Left icon component |
| `title` | `string` | **(required)** | Main title text |
| `description` | `ReactNode` | — | Description below the title |
| `middleText` | `string` | — | Text below the description |
| `rightChildren` | `ReactNode` | — | Content beside the title (in the content line) |
| `variant` | `LineItemLayoutVariant` | `"main-content"` | Size variant (see table above) |
| `width` | `"auto" \| "fit" \| "full"` | `"full"` | Container width mode |
| `strikethrough` | `boolean` | `false` | Line-through on title |
| `loading` | `boolean` | `false` | Show skeleton placeholders |
| `center` | `boolean` | `false` | Vertically center icon with content |

## Usage examples

```tsx
import { LineItemLayout } from "@opal/components";
import { SvgUser, SvgStar, SvgActions } from "@opal/icons";

// Main Content (default) — prominent list item
<LineItemLayout
  icon={SvgStar}
  title="Featured Agent"
  description="A specialized assistant for code review"
  rightChildren={<Button>Edit</Button>}
/>

// Main UI — standard list item
<LineItemLayout
  icon={SvgUser}
  title="Instructions"
  description={agent.system_prompt}
  variant="main-ui"
/>

// Secondary — compact metadata label
<LineItemLayout
  icon={SvgActions}
  title="3 Actions"
  variant="secondary"
/>

// Section — section heading
<LineItemLayout
  icon={SvgStar}
  title="Data Sources"
  description="Connected integrations"
  variant="section"
/>

// Headline — page-level heading
<LineItemLayout
  icon={SvgStar}
  title="Agent Settings"
  description="Configure your agent's behavior"
  variant="headline"
/>

// Loading state
<LineItemLayout
  icon={SvgUser}
  title=""
  description="placeholder"
  rightChildren={<div />}
  loading
/>
```

## Migration from legacy LineItemLayout

| Legacy variant | Opal variant |
|----------------|--------------|
| `"primary"` | `"main-content"` |
| `"secondary"` | `"main-ui"` |
| `"tertiary"` | `"main-ui"` |
| `"tertiary-muted"` | `"main-ui"` |
| `"mini"` | `"secondary"` |

| Legacy prop | Opal equivalent |
|-------------|-----------------|
| `icon` | `icon` (now `IconFunctionComponent` from `@opal/types`) |
| `title` | `title` |
| `description` | `description` |
| `middleText` | `middleText` |
| `rightChildren` | `rightChildren` (now inside content line, beside title) |
| `variant` | `variant` (renamed values — see table above) |
| `width` | `width` |
| `strikethrough` | `strikethrough` |
| `loading` | `loading` |
| `center` | `center` |
| `reducedPadding` | **Removed** — use parent padding instead |
