# IllustrationContent

**Import:** `import { IllustrationContent, type IllustrationContentProps } from "@opal/layouts";`

A vertically-stacked, center-aligned layout for empty states, error pages, and informational placeholders. Pairs a large illustration with a title and optional description.

## Why IllustrationContent?

Empty states and placeholder screens share a recurring pattern: a large illustration centered above a title and description. `IllustrationContent` standardises that pattern so every empty state looks consistent without hand-rolling flex containers and spacing each time.

## Layout Structure

```
┌─────────────────────────────────┐
│          (1.25rem pad)          │
│     ┌───────────────────┐       │
│     │   illustration    │       │
│     │   7.5rem × 7.5rem │       │
│     └───────────────────┘       │
│         (0.75rem gap)           │
│          title (center)         │
│         (0.75rem gap)           │
│      description (center)       │
│          (1.25rem pad)          │
└─────────────────────────────────┘
```

- Outer container: `flex flex-col items-center text-center` with `1.25rem` padding.
- Gap between all children: `0.75rem`.
- Illustration: rendered at `7.5rem × 7.5rem` (120px), no extra padding.
- Title: `font-main-content-emphasis text-text-04`.
- Description: `font-secondary-body text-text-03`.

## Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `illustration` | `IconFunctionComponent` | — | Optional illustration component rendered at 7.5rem × 7.5rem, centered. Works with any `@opal/illustrations` SVG. |
| `title` | `string` | **(required)** | Main title text, center-aligned. |
| `description` | `string` | — | Optional description below the title, center-aligned. |

## Usage Examples

### Empty search results

```tsx
import { IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";

<IllustrationContent
  illustration={SvgNoResult}
  title="No results found"
  description="Try adjusting your search or filters."
/>
```

### Not found page

```tsx
import { IllustrationContent } from "@opal/layouts";
import SvgNotFound from "@opal/illustrations/not-found";

<IllustrationContent
  illustration={SvgNotFound}
  title="Page not found"
  description="The page you're looking for doesn't exist or has been moved."
/>
```

### Title only (no illustration, no description)

```tsx
import { IllustrationContent } from "@opal/layouts";

<IllustrationContent title="Nothing here yet" />
```

### Empty state with illustration and title (no description)

```tsx
import { IllustrationContent } from "@opal/layouts";
import SvgEmpty from "@opal/illustrations/empty";

<IllustrationContent
  illustration={SvgEmpty}
  title="No items"
/>
```
