# Settings Layouts

**Import:** `import { SettingsLayouts } from "@opal/layouts";`

Namespaced layout primitives for admin/settings pages. Provides a standardized
structure with a sticky scroll-aware header, centered content container, and body region.

## Components

### Root

Scrollable wrapper that centers content at a configurable max-width.

| Prop    | Type                                        | Default | Description                           |
| ------- | ------------------------------------------- | ------- | ------------------------------------- |
| `width` | `"sm" \| "sm-md" \| "md" \| "lg" \| "full"` | `"md"`  | Max-width of the inner content column |

Width presets map to CSS variables defined by the app (`--app-container-*`):
`sm` = 672px, `sm-md` = 752px, `md` = 872px, `lg` = 992px, `full` = 100%.

### Header

Sticky page header with icon, title, optional description, and action slots.
Automatically shows a scroll shadow when the page has scrolled down.
Headers are only sticky when `actions` is non-empty.

| Prop            | Type                    | Default | Description                                               |
| --------------- | ----------------------- | ------- | --------------------------------------------------------- |
| `icon`          | `IconFunctionComponent` | —       | Page icon (required)                                      |
| `moreIcon1`     | `IconFunctionComponent` | —       | Second icon in the title's icon row (see `Content`)       |
| `moreIcon2`     | `IconFunctionComponent` | —       | Third icon in the title's icon row (see `Content`)        |
| `title`         | `string`                | —       | Page title (required)                                     |
| `description`   | `string`                | —       | Subtitle below the title                                  |
| `actions`       | `ReactNode[]`           | —       | Controls right of the title, left to right, each with a `key`; top-aligned row with a 0.5rem gap, 1rem from the title block. Also enables sticky behavior |
| `children`      | `ReactNode`             | —       | Content below the title row (e.g. search bar, filters)    |
| `cancel`        | `boolean \| () => void` | `false` | Render a secondary Cancel as the first action; `true` goes back in history, a function overrides the destination |
| `divider`       | `boolean`               | `false` | Show a horizontal divider at the bottom of the header     |

### Body

Content container with consistent padding and vertical spacing.

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
