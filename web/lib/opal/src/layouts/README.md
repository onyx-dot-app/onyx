# @opal/layouts

**Import:** `import { Content, ContentAction, ErrorState, IllustrationContent, KeyValue, PageCenter, StickyBox } from "@opal/layouts";`

Layout primitives for composing content blocks. These components handle sizing, font selection, icon alignment, and optional inline editing — things that are tedious to get right by hand and easy to get wrong.

## Components

| Component                                                 | Description                                                                                                                                               | Docs                                                           |
| --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| [`Content`](./content/README.md)                          | Icon + title + description. The title `font` sets every size; `orientation` places the icon. | [Content README](./content/README.md)                          |
| [`ContentAction`](./content-action/README.md)             | Wraps `Content` in a flex-row with an optional `rightChildren` slot for action buttons. Adds padding alignment with adjacent interactive elements.        | [ContentAction README](./content-action/README.md)             |
| [`IllustrationContent`](./illustration-content/README.md) | Center-aligned illustration + title + description stack for empty states, error pages, and placeholders.                                                  | [IllustrationContent README](./illustration-content/README.md) |
| [`PageCenter`](./page-center/README.md) | Centres a whole-body state (loading, error, empty) in the page body, both ways. | [PageCenter README](./page-center/README.md) |
| [`StickyBox`](./sticky-box/README.md) | A block that pins to the top or bottom of its scroll container as the page scrolls past it, with an optional shadow while pinned. | [StickyBox README](./sticky-box/README.md) |
| [`ErrorState`](./states/README.md) | Content that failed to load, centred in place of a page body or list. | [States README](./states/README.md) |
| [`KeyValue`](./key-value/README.md) | One read-only "label … value" row, for details of a saved object. | [KeyValue README](./key-value/README.md) |

## Quick Start

```tsx
import { Content, ContentAction, IllustrationContent } from "@opal/layouts";
import { Button } from "@opal/components";
import SvgSettings from "@opal/icons/settings";
import SvgNoResult from "@opal/illustrations/no-result";

// Simple heading
<Content font="heading-headline" orientation="stacked"
  icon={SvgSettings}
  title="Account Settings"
  description="Manage your preferences"
/>

// Label with tag
<Content font="main-content-emphasis"
  icon={SvgSettings}
  title="OpenAI"
  description="GPT"
  badge={{ title: "Default", color: "info" }}
/>

// Row with action button
<ContentAction font="main-content-emphasis"
  icon={SvgSettings}
  title="Provider Name"
  description="Some description"
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

### One font-driven component (`Content`)

`Content` is one component with two layout props:

- **`font`** — the title's `TextFont`. Every size derives from it: an icon box is one title line tall
  (`1lh`), with 2px padding.
- **`orientation`** — `inline`, `reverse` or `stacked` (icon before, after or above the title).

See the [Content README](./content/README.md).

### Padding alignment (`ContentAction`)

`ContentAction.padding` is a spacing step (`N / 4` rem), narrowed to `0 | 0.5 | 1 | 2`. Those four
are exactly the paddings `Interactive.Container` applies at its size presets, so a content row still
lines up with an adjacent button of the same size — `lg` → `2`, `md` and `sm` → `1`, `xs` and `2xs`
→ `0.5`, `fit` → `0`.

## Exports

From `@opal/layouts`:

```ts
// Components
Content;
ContentAction;
ErrorState;
IllustrationContent;
KeyValue;
PageCenter;
StickyBox;

// Types
ContentProps;
ContentActionProps;
ErrorStateProps;
IllustrationContentProps;
KeyValueProps;
PageCenterProps;
StickyBoxRootProps;
ContentOrientation;
ContentBadge;
ContentEditHandle;
```

