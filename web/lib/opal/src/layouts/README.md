# @opal/layouts

**Import:** `import { Content, ContentAction, IllustrationContent } from "@opal/layouts";`

Layout primitives for composing content blocks. These components handle sizing, font selection, icon alignment, and optional inline editing — things that are tedious to get right by hand and easy to get wrong.

## Components

| Component | Description | Docs |
|---|---|---|
| [`Content`](./content/README.md) | Icon + title + description row. Routes to an internal layout (`ContentXl`, `ContentLg`, `ContentMd`, or `ContentSm`) based on `sizePreset` and `variant`. | [Content README](./content/README.md) |
| [`ContentAction`](./content-action/README.md) | Wraps `Content` in a flex-row with an optional `rightChildren` slot for action buttons. Adds padding alignment with adjacent interactive elements. | [ContentAction README](./content-action/README.md) |
| [`IllustrationContent`](./illustration-content/README.md) | Center-aligned illustration + title + description stack for empty states, error pages, and placeholders. | [IllustrationContent README](./illustration-content/README.md) |

## Quick Start

```tsx
import { Content, ContentAction, IllustrationContent } from "@opal/layouts";
import { Button } from "@opal/components";
import SvgSettings from "@opal/icons/settings";
import SvgNoResult from "@opal/illustrations/no-result";

// Simple heading
<Content
  icon={SvgSettings}
  title="Account Settings"
  description="Manage your preferences"
  sizePreset="headline"
  variant="heading"
/>

// Label with tag
<Content
  icon={SvgSettings}
  title="OpenAI"
  description="GPT"
  sizePreset="main-content"
  variant="section"
  tag={{ title: "Default", color: "blue" }}
/>

// Row with action button
<ContentAction
  icon={SvgSettings}
  title="Provider Name"
  description="Some description"
  sizePreset="main-content"
  variant="section"
  padding={2}
  rightChildren={
    <Button icon={SvgSettings} prominence="tertiary" />
  }
/>

// Empty state with illustration
<IllustrationContent
  illustration={SvgNoResult}
  title="No results found"
  description="Try adjusting your search or filters."
/>
```

## Architecture

### Two-axis design (`Content`)

`Content` uses a two-axis system:

- **`sizePreset`** — controls sizing tokens (icon size, padding, gap, font, line-height).
- **`variant`** — controls structural layout (icon placement, description rendering).

Valid preset/variant combinations are enforced at the type level via a discriminated union. See the [Content README](./content/README.md) for the full matrix.

### Padding alignment (`ContentAction`)

`ContentAction.padding` is a spacing step (`N / 4` rem), narrowed to `0 | 0.5 | 1 | 2`. Those four
are exactly the paddings `Interactive.Container` applies at its size presets, so a content row still
lines up with an adjacent button of the same size — `lg` → `2`, `md` and `sm` → `1`, `xs` and `2xs`
→ `0.5`, `fit` → `0`.

## Exports

From `@opal/layouts`:

```ts
// Components
Content
ContentAction
IllustrationContent

// Types
ContentProps
ContentActionProps
IllustrationContentProps
SizePreset
ContentVariant
```

## Internal Layout Components

These are not exported — `Content` routes to them automatically:

| Layout | Used when | File |
|---|---|---|
| `ContentXl` | `sizePreset` is `headline` or `section` with `variant="heading"` | `content/ContentXl.tsx` |
| `ContentLg` | `sizePreset` is `headline` or `section` with `variant="section"` | `content/ContentLg.tsx` |
| `ContentMd` | `sizePreset` is `main-content`, `main-ui`, or `secondary` with `variant="section"` | `content/ContentMd.tsx` |
| `ContentSm` | `variant="body"` | `content/ContentSm.tsx` |
