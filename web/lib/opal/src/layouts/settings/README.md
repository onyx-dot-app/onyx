# Settings Layouts

**Import:** `import { SettingsLayouts } from "@opal/layouts";`

Namespaced layout primitives for admin/settings pages. Provides a standardized
structure with a sticky scroll-aware header, centered content container, and body region.

## Components

### Root

Scrollable wrapper that centers content at a configurable max-width. It also
holds the page's state, which `Body` renders. It always reserves the scrollbar
gutter, so a page keeps the same width whether its content scrolls or not.
Pages that share a frame (e.g. settings tabs) do not shift when you switch
between them.

| Prop    | Type                                        | Default | Description                           |
| ------- | ------------------------------------------- | ------- | ------------------------------------- |
| `width` | `"sm" \| "md" \| "lg" \| "xl" \| "full"`    | `"md"`  | Max-width of the inner content column |
| `animateEnter` | `boolean` | `true` | Animate the body in when the page mounts; `false` renders it at once |
| `loading` | `boolean` | `false` | The body shows the page loader in place of its children. When it turns `false`, the children mount and animate in |
| `error` | `boolean \| string \| RichStr` | `false` | The body shows the standard error state in place of its children, titled "{header title} failed to load". A string or `markdown()` is the description; `true` uses a generic one. It wins over `loading` |

Width presets map to CSS variables defined by the app (`--app-container-*`):
`sm` = 672px, `md` = 872px, `lg` = 992px, `xl` = 1120px, `full` = 100%.

### Header

Sticky page header with icon, title, optional description, and action slots.
Automatically shows a scroll shadow when the page has scrolled down.
Headers are only sticky when `actions` is non-empty.

| Prop             | Type                      | Default | Description                                                                                                                                               |
| ---------------- | ------------------------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `icon`           | `IconFunctionComponent`   | —       | Optional page icon                                                                                                                                      |
| `moreIcon1`      | `IconFunctionComponent`   | —       | Second icon in the title's icon row (see `Content`)                                                                                                       |
| `moreIcon2`      | `IconFunctionComponent`   | —       | Third icon in the title's icon row (see `Content`)                                                                                                        |
| `title`          | `string`                  | —       | Page title (required)                                                                                                                                     |
| `description`    | `string`                  | —       | Subtitle below the title                                                                                                                                  |
| `descriptionTag` | `TagProps`                | —       | Tag inline after the description, e.g. a status                                                                                                           |
| `editable`       | `boolean`                 | `false` | The title can be edited in place (see `Content`)                                                                                                          |
| `editButton`     | `"hover" \| "rest"`       | `"hover"` | When the editable title shows its pencil: on hover, or at rest too (see `Content`)                                                                      |
| `onTitleChange`  | `(title: string) => void` | —       | Called when the user commits a title edit                                                                                                                 |
| `actions`        | `ReactNode[]`             | —       | Controls right of the title, left to right, each with a `key`; top-aligned row with a 0.5rem gap, 1rem from the title block. Also enables sticky behavior |
| `children`       | `ReactNode`               | —       | Content below the title row (e.g. search bar, filters)                                                                                                    |
| `cancel`         | `boolean \| () => void`   | `false` | Render a secondary Cancel as the first action; `true` goes back in history, a function overrides the destination                                          |
| `divider`        | `boolean`                 | `false` | Show a horizontal divider at the bottom of the header                                                                                                     |
| `stackActionsOnMobile` | `boolean`               | `false` | Place actions below the title on a full-width row on narrow screens                                                                                       |

### Body

Content container with consistent padding and vertical spacing. It renders
the state set on `Root`: the error state when `error` is set (the
broken-plug illustration, centred, with the page title and the
description), else the page loader while `loading`, and otherwise its
children, animated in with [`Enter`](../../components/enter/README.md) unless
`animateEnter` is `false`. The header stays still, and reports its title to
`Root` for the error title.

| Prop    | Type      | Default | Description                                         |
| ------- | --------- | ------- | --------------------------------------------------- |
| `gap`   | `Spacing` | `8`     | Space between sections, as a spacing step (N/4 rem) |

## Usage

```tsx
import { SettingsLayouts } from "@opal/layouts";

<SettingsLayouts.Root>
  <SettingsLayouts.Header
    icon={SvgSettings}
    title="Account Settings"
    description="Manage your preferences"
    actions={[
      <Button key="save" onClick={save}>
        Save
      </Button>,
    ]}
  >
    <InputTypeIn placeholder="Search settings..." />
  </SettingsLayouts.Header>

  <SettingsLayouts.Body>
    <Card>Settings content</Card>
  </SettingsLayouts.Body>
</SettingsLayouts.Root>

// With a Cancel action
<SettingsLayouts.Header
  icon={SvgArrow}
  title="Edit Item"
  cancel={() => router.push("/admin/items")}
/>
```
