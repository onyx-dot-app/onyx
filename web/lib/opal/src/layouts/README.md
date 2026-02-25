# @opal/layouts

**Import:** `import { Content, ContentAction } from "@opal/layouts";`

Layout primitives for composing icon + title + description rows. These components handle sizing, font selection, icon alignment, and optional inline editing — things that are tedious to get right by hand and easy to get wrong.

## Components

| Component | Description | Docs |
|---|---|---|
| [`Content`](./Content/README.md) | Icon + title + description row. Routes to an internal layout (`HeadingLayout`, `LabelLayout`, or `BodyLayout`) based on `sizePreset` and `variant`. | [Content README](./Content/README.md) |
| [`ContentAction`](./ContentAction/README.md) | Wraps `Content` in a flex-row with an optional `rightChildren` slot for action buttons. Adds padding alignment via the shared `SizeVariant` scale. | [ContentAction README](./ContentAction/README.md) |

## Quick Start

```tsx
import { Content, ContentAction } from "@opal/layouts";
import { Button } from "@opal/components";
import SvgSettings from "@opal/icons/settings";

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
  paddingVariant="lg"
  rightChildren={
    <Button icon={SvgSettings} prominence="tertiary" />
  }
/>
```

## Architecture

### Two-axis design (`Content`)

`Content` uses a two-axis system:

- **`sizePreset`** — controls sizing tokens (icon size, padding, gap, font, line-height).
- **`variant`** — controls structural layout (icon placement, description rendering).

Valid preset/variant combinations are enforced at the type level via a discriminated union. See the [Content README](./Content/README.md) for the full matrix.

### Shared size scale (`ContentAction`)

`ContentAction` uses the same `SizeVariant` scale (`lg`, `md`, `sm`, `xs`, `2xs`, `fit`) defined in `@opal/shared` that powers `Interactive.Container` and `Button`. This ensures that padding on content rows aligns with adjacent interactive elements at the same size.

## Exports

From `@opal/layouts`:

```ts
// Components
Content
ContentAction

// Types
ContentProps
ContentActionProps
SizePreset
ContentVariant
```

## Internal Layout Components

These are not exported — `Content` routes to them automatically:

| Layout | Used when | File |
|---|---|---|
| `HeadingLayout` | `sizePreset` is `headline` or `section` | `Content/HeadingLayout.tsx` |
| `LabelLayout` | `sizePreset` is `main-content`, `main-ui`, or `secondary` with `variant="section"` | `Content/LabelLayout.tsx` |
| `BodyLayout` | `variant="body"` | `Content/BodyLayout.tsx` |
