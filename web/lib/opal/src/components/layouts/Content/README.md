# Content

**Import:** `import { Content, type ContentProps } from "@opal/components";`

A two-axis layout component for displaying icon + title + description rows. Routes to an internal layout based on the `sizePreset` and `variant` combination.

## Two-Axis Architecture

### `sizePreset` — controls sizing (icon, padding, gap, font)

| Preset | Icon | Container padding | Gap | Title font | Line-height |
|---|---|---|---|---|---|
| `headline` | 2rem (32px) | `p-0.5` (2px) | 0.25rem (4px) | `font-heading-h2` | 2.25rem (36px) |
| `section` | 1.25rem (20px) | `p-1` (4px) | 0rem | `font-heading-h3` | 1.75rem (28px) |
| `main-content` | 1.125rem | `p-[0.1875rem]` | 0.125rem | `font-main-content-emphasis` | 1.5rem |
| `main-ui` | 1rem | `p-0.5` | 0.25rem | `font-main-ui-action` | 1.25rem |
| `secondary` | 0.75rem | `p-0.5` | 0.125rem | `font-secondary-action` | 1rem |

> Icon container height (icon + 2 × padding) always equals the title line-height.

### `variant` — controls structure / layout

| variant | Description |
|---|---|
| `heading` | Icon on **top** (flex-col) — HeadingLayout |
| `section` | Icon **inline** (flex-row) — HeadingLayout (or LabelLayout for smaller presets) |
| `body` | Body text layout — BodyLayout (future) |

### Valid Combinations → Internal Routing

| sizePreset | variant | Routes to |
|---|---|---|
| `headline` / `section` | `heading` | **HeadingLayout** (icon on top) |
| `headline` / `section` | `section` | **HeadingLayout** (icon inline) |
| `main-content` / `main-ui` / `secondary` | `section` | LabelLayout (future) |
| `main-content` / `main-ui` / `secondary` | `body` | BodyLayout (future) |

Invalid combinations (e.g. `sizePreset="headline" + variant="body"`) are excluded at the type level.

## Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `sizePreset` | `SizePreset` | `"headline"` | Size preset (see table above) |
| `variant` | `ContentVariant` | `"heading"` | Layout variant (see table above) |
| `icon` | `IconFunctionComponent` | — | Optional icon component |
| `title` | `string` | **(required)** | Main title text |
| `description` | `string` | — | Description below the title |
| `editable` | `boolean` | `false` | Enable inline editing of the title |
| `onTitleChange` | `(newTitle: string) => void` | — | Called when user commits an edit |

## Architecture

```
div.opal-content-heading                          <- outer flex (row or col)
  +- div.opal-content-heading-icon-container      <- sized icon wrapper (centered)
  |    +- Icon                                    (sized per sizePreset)
  +- div.opal-content-heading-body                <- flex-1 column
       +- div.opal-content-heading-title-row      <- flex row (title + edit button)
       |    +- span.opal-content-heading-title    (or input when editing)
       |    +- div.opal-content-heading-edit-button
       +- div.opal-content-heading-description    <- secondary body text
```

## Usage Examples

```tsx
import { Content } from "@opal/components";
import SvgSearch from "@opal/icons/search";

// Headline heading — large, icon on top
<Content
  icon={SvgSearch}
  sizePreset="headline"
  variant="heading"
  title="Agent Settings"
  description="Configure your agent's behavior"
/>

// Headline section — large, icon inline
<Content
  icon={SvgSearch}
  sizePreset="headline"
  variant="section"
  title="Agent Settings"
  description="Configure your agent's behavior"
/>

// Section heading — medium, icon on top
<Content
  icon={SvgSearch}
  sizePreset="section"
  variant="heading"
  title="Data Sources"
  description="Connected integrations"
/>

// Section section — medium, icon inline
<Content
  icon={SvgSearch}
  sizePreset="section"
  variant="section"
  title="Data Sources"
  description="Connected integrations"
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
