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

#### ContentSm presets (variant="body")

| Preset | Icon | Icon padding | Gap | Title font | Line-height |
|---|---|---|---|---|---|
| `main-content` | 1rem (16px) | `p-1` (4px) | 0.125rem (2px) | `font-main-content-body` | 1.5rem (24px) |
| `main-ui` | 1rem (16px) | `p-0.5` (2px) | 0.25rem (4px) | `font-main-ui-action` | 1.25rem (20px) |
| `secondary` | 0.75rem (12px) | `p-0.5` (2px) | 0.125rem (2px) | `font-secondary-action` | 1rem (16px) |

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

### Common props (all variants)

| Prop | Type | Default | Description |
|---|---|---|---|
| `sizePreset` | `SizePreset` | `"headline"` | Size preset (see tables above) |
| `variant` | `ContentVariant` | `"heading"` | Layout variant |
| `icon` | `IconFunctionComponent` | — | Optional icon component |
| `title` | `string` | **(required)** | Main title text |
| `description` | `string` | — | Optional description (not available for `variant="body"`) |
| `editable` | `boolean` | `false` | Enable inline editing (not available for `variant="body"`) |
| `onTitleChange` | `(newTitle: string) => void` | — | Called when user commits an edit |
| `widthVariant` | `WidthVariant` | `"auto"` | `"auto"` shrink-wraps, `"full"` stretches |
| `withInteractive` | `boolean` | — | Opts title into `Interactive.Base`'s `--interactive-foreground` color |
| `ref` | `React.Ref<HTMLDivElement>` | — | Ref forwarded to the root `<div>` of the resolved layout |

### ContentXl-only props (`variant="heading"`)

| Prop | Type | Default | Description |
|---|---|---|---|
| `moreIcon1` | `IconFunctionComponent` | — | Secondary icon in icon row |
| `moreIcon2` | `IconFunctionComponent` | — | Tertiary icon in icon row |

### ContentMd-only props (`sizePreset="main-content" / "main-ui" / "secondary"`, `variant="section"`)

| Prop | Type | Default | Description |
|---|---|---|---|
| `optional` | `boolean` | — | Renders "(Optional)" beside the title |
| `auxIcon` | `"info-gray" \| "info-blue" \| "warning" \| "error"` | — | Auxiliary status icon beside the title |
| `tag` | `TagProps` | — | Tag rendered beside the title |

### ContentSm-only props (`variant="body"`)

| Prop | Type | Default | Description |
|---|---|---|---|
| `orientation` | `"vertical" \| "inline" \| "reverse"` | `"inline"` | Layout orientation |
| `prominence` | `"default" \| "muted" \| "muted-2x"` | `"default"` | Title prominence |

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

// ContentLg — section, icon inline
<Content
  icon={SvgSearch}
  sizePreset="section"
  variant="section"
  title="Data Sources"
/>

// ContentMd — with tag and optional marker
<Content
  icon={SvgSearch}
  sizePreset="main-ui"
  title="Instructions"
  tag={{ title: "New", color: "green" }}
  optional
/>

// ContentSm — body text
<Content
  icon={SvgSearch}
  sizePreset="main-ui"
  variant="body"
  title="Last updated 2 hours ago"
  prominence="muted"
/>

// Editable title
<Content
  sizePreset="headline"
  variant="heading"
  title="My Agent"
  editable
  onTitleChange={(newTitle) => save(newTitle)}
/>
```
