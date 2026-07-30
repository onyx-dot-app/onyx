# ContentAction

**Import:** `import { ContentAction, type ContentActionProps } from "@opal/layouts";`

A row layout that pairs a [`Content`](../content/README.md) block with optional right-side action children (buttons, badges, icons, etc.).

## Why ContentAction?

`Content` renders icon + title + description but has no slot for actions. When you need a settings row, card header, or list item with an action on the right you would typically wrap `Content` in a manual flex-row. `ContentAction` standardises that pattern and adds padding alignment with `Interactive.Container` and `Button` via the shared `SizeVariant` scale.

## Props

Inherits **all** props from [`Content`](../content/README.md) (same discriminated-union API) plus:

| Prop | Type | Default | Description |
|---|---|---|---|
| `rightChildren` | `ReactNode` | `undefined` | Content rendered on the right side. Wrapper stretches to the full height of the row. |
| `padding` | `SizeVariant` | `"lg"` | Padding preset applied around the `Content` area. Uses the shared size scale from `@opal/shared`. |
| `fillRight` | `boolean` | `false` | When `true`, the `rightChildren` column grows to fill the row (capped at `--block-width-form-input-column-max`, 240px) instead of hugging its content. Use for full-width form inputs; leave off for compact controls like toggles/buttons. Ignored in the `responsive` branch. |

### `padding` reference

| Value | Padding class | Effective padding |
|---|---|---|
| `lg` | `p-2` | 0.5rem (8px) |
| `md` | `p-1` | 0.25rem (4px) |
| `sm` | `p-1` | 0.25rem (4px) |
| `xs` | `p-0.5` | 0.125rem (2px) |
| `2xs` | `p-0.5` | 0.125rem (2px) |
| `fit` | `p-0` | 0 |

These values are identical to the padding applied by `Interactive.Container` at each size, so `ContentAction` labels naturally align with adjacent buttons of the same size.

## Layout Structure

```
[  Content (flex-1, padded)  ][  rightChildren (shrink-0, full height)  ]
```

- The outer wrapper is `flex flex-row items-stretch w-full`.
- `Content` sits inside a `flex-1 min-w-0` div with padding from `padding`.
- `rightChildren` is wrapped in `flex items-stretch shrink-0` so it stretches vertically.
- With `fillRight`, the `rightChildren` wrapper instead becomes `flex-1 min-w-0` with a
  `max-width: var(--block-width-form-input-column-max)` (240px) cap, so the input grows to fill
  the row up to the Figma input-column width. The child input keeps its own `w-full` +
  `min-width` floor.

## Usage Examples

### Settings row with an edit button

```tsx
import { ContentAction } from "@opal/layouts";
import { Button } from "@opal/components";
import SvgSettings from "@opal/icons/settings";

<ContentAction
  icon={SvgSettings}
  title="OpenAI"
  description="GPT"
  sizePreset="main-content"
  variant="section"
  tag={{ title: "Default", color: "blue" }}
  padding="lg"
  rightChildren={
    <Button icon={SvgSettings} prominence="tertiary" onClick={handleEdit} />
  }
/>
```

### Card header with connect action

```tsx
import { ContentAction } from "@opal/layouts";
import { Button } from "@opal/components";
import { SvgArrowExchange, SvgCloud } from "@opal/icons";

<ContentAction
  icon={SvgCloud}
  title="Google Cloud Vertex AI"
  description="Gemini"
  sizePreset="main-content"
  variant="section"
  padding="md"
  rightChildren={
    <Button rightIcon={SvgArrowExchange} prominence="tertiary">
      Connect
    </Button>
  }
/>
```

### Full-width form input (`fillRight`)

```tsx
import { ContentAction } from "@opal/layouts";
import { InputSelect } from "@/refresh-components/inputs/InputSelect";

<ContentAction
  title="Query History Visibility"
  description="Control what is shown in query history"
  sizePreset="main-ui"
  variant="section"
  fillRight
  rightChildren={<InputSelect ... />}
/>
```

The select grows to fill the row (up to 240px) instead of sitting at its content width. Compact
controls like `Switch`/`Button` should omit `fillRight` so they keep hugging the right edge.

### No right children (padding-only wrapper)

```tsx
<ContentAction
  title="Section Header"
  sizePreset="main-content"
  variant="section"
  padding="lg"
/>
```

When `rightChildren` is omitted the component renders only the padded `Content` — useful for alignment consistency when some rows have actions and others don't.
