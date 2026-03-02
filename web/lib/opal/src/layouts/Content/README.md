# Content

**Import:** `import { Content, type ContentProps } from "@opal/layouts";`

A two-axis layout component for displaying icon + title + description rows. Routes to an internal layout based on the `sizePreset` and `variant` combination.

## Two-Axis Architecture

### `sizePreset` — controls sizing (icon, padding, gap, font)

#### ContentXl presets (variant="heading")

| Preset | Icon | Icon padding | moreIcon1 | mI1 padding | moreIcon2 | mI2 padding | Title font | Line-height |
|---|---|---|---|---|---|---|---|---|
| `headline` | 2rem (32px) | `p-0.5` (2px) | 1rem (16px) | `p-0.5` (2px) | 2rem (32px) | `p-0.5` (2px) | `font-heading-h2` | 2.25rem (36px) |
| `section` | 1.5rem (24px) | `p-0.5` (2px) | 0.75rem (12px) | `p-0.5` (2px) | 1.5rem (24px) | `p-0.5` (2px) | `font-heading-h3` | 1.75rem (28px) |

#### ContentLg presets (variant="section")

| Preset | Icon | Icon padding | Gap | Title font | Line-height |
|---|---|---|---|---|---|
| `headline` | 2rem (32px) | `p-0.5` (2px) | 0.25rem (4px) | `font-heading-h2` | 2.25rem (36px) |
| `section` | 1.25rem (20px) | `p-1` (4px) | 0rem | `font-heading-h3-muted` | 1.75rem (28px) |

#### ContentMd presets

| Preset | Icon | Icon padding | Icon color | Gap | Title font | Line-height |
|---|---|---|---|---|---|---|
| `main-content` | 1rem (16px) | `p-1` (4px) | `text-04` | 0.125rem (2px) | `font-main-content-emphasis` | 1.5rem (24px) |
| `main-ui` | 1rem (16px) | `p-0.5` (2px) | `text-03` | 0.25rem (4px) | `font-main-ui-action` | 1.25rem (20px) |
| `secondary` | 0.75rem (12px) | `p-0.5` (2px) | `text-04` | 0.125rem (2px) | `font-secondary-action` | 1rem (16px) |

> Icon container height (icon + 2 x padding) always equals the title line-height.

### `variant` — controls structure / layout

| variant | Description |
|---|---|
| `heading` | Icon on **top** (flex-col) — ContentXl |
| `section` | Icon **inline** (flex-row) — ContentLg or ContentMd |
| `body` | Body text layout — ContentSm |

### Valid Combinations -> Internal Routing

| sizePreset | variant | Routes to |
|---|---|---|
| `headline` / `section` | `heading` | **ContentXl** (icon on top) |
| `headline` / `section` | `section` | **ContentLg** (icon inline) |
| `main-content` / `main-ui` / `secondary` | `section` | **ContentMd** |
| `main-content` / `main-ui` / `secondary` | `body` | **ContentSm** |

Invalid combinations (e.g. `sizePreset="headline" + variant="body"`) are excluded at the type level.

## Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `sizePreset` | `SizePreset` | `"headline"` | Size preset (see tables above) |
| `variant` | `ContentVariant` | `"heading"` | Layout variant (see table above) |
| `icon` | `IconFunctionComponent` | — | Optional icon component |
| `title` | `string` | **(required)** | Main title text |
| `description` | `string` | — | Optional description below the title |
| `editable` | `boolean` | `false` | Enable inline editing of the title |
| `onTitleChange` | `(newTitle: string) => void` | — | Called when user commits an edit |
| `moreIcon1` | `IconFunctionComponent` | — | Secondary icon in icon row (ContentXl only) |
| `moreIcon2` | `IconFunctionComponent` | — | Tertiary icon in icon row (ContentXl only) |

## Internal Layouts

### ContentXl

For `headline` / `section` presets with `variant="heading"`. Icon row on top (flex-col), supports `moreIcon1` and `moreIcon2` in the icon row. Description is always `font-secondary-body text-text-03`.

### ContentLg

For `headline` / `section` presets with `variant="section"`. Always inline (flex-row). Description is always `font-secondary-body text-text-03`.

### ContentMd

For `main-content` / `main-ui` / `secondary` presets. Always inline. Both `icon` and `description` are optional. Description is always `font-secondary-body text-text-03`.

## Usage Examples

```tsx
import { Content } from "@opal/layouts";
import SvgSearch from "@opal/icons/search";

// ContentXl — headline, icon on top
<Content
  icon={SvgSearch}
  sizePreset="headline"
  variant="heading"
  title="Agent Settings"
  description="Configure your agent's behavior"
/>

// ContentXl — with more icons
<Content
  icon={SvgSearch}
  sizePreset="headline"
  variant="heading"
  title="Agent Settings"
  moreIcon1={SvgStar}
  moreIcon2={SvgLock}
/>

// ContentLg — section, icon inline
<Content
  icon={SvgSearch}
  sizePreset="section"
  variant="section"
  title="Data Sources"
  description="Connected integrations"
/>

// ContentMd — with icon and description
<Content
  icon={SvgSearch}
  sizePreset="main-ui"
  title="Instructions"
  description="Agent system prompt"
/>

// ContentMd — title only (no icon, no description)
<Content
  sizePreset="main-content"
  title="Featured Agent"
/>

// Editable title
<Content
  icon={SvgSearch}
  sizePreset="headline"
  variant="heading"
  title="My Agent"
  editable
  onTitleChange={(newTitle) => save(newTitle)}
/>
```
