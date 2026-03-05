# ContentAction

**Import:** `import { ContentAction, type ContentActionProps } from "@opal/layouts";`

A row layout that pairs a [`Content`](../Content/README.md) block with optional right-side action children (buttons, badges, icons, etc.).

## Why ContentAction?

`Content` renders icon + title + description but has no slot for actions. When you need a settings row, card header, or list item with an action on the right, `ContentAction` standardises that pattern and adds padding alignment with `Interactive.Container` and `Button` via the shared `SizeVariant` scale.

## Props

Inherits **all** props from [`Content`](../Content/README.md) (same discriminated-union API, including `widthVariant`, `withInteractive`, etc.) plus:

| Prop | Type | Default | Description |
|---|---|---|---|
| `rightChildren` | `ReactNode` | — | Content rendered on the right side. Wrapper stretches to the full height of the row. |
| `paddingVariant` | `SizeVariant` | `"lg"` | Padding preset applied around the `Content` area. |
| `ref` | `React.Ref<HTMLDivElement>` | — | Ref forwarded to the root `<div>`. |

### `paddingVariant` reference

| Value | Padding class | Effective padding |
|---|---|---|
| `lg` | `p-2` | 0.5rem (8px) |
| `md` | `p-1` | 0.25rem (4px) |
| `sm` | `p-1` | 0.25rem (4px) |
| `xs` | `p-0.5` | 0.125rem (2px) |
| `2xs` | `p-0.5` | 0.125rem (2px) |
| `fit` | `p-0` | 0 |

## Layout Structure

```
[  Content (flex-1, padded)  ][  rightChildren (shrink-0, full height)  ]
```

- The outer wrapper is `flex flex-row items-stretch w-full`.
- `Content` sits inside a `flex-1 min-w-0` div with padding from `paddingVariant`.
- `rightChildren` is wrapped in `flex items-stretch shrink-0` so it stretches vertically.

## Usage Examples

```tsx
import { ContentAction } from "@opal/layouts";
import { Button } from "@opal/components";
import SvgSettings from "@opal/icons/settings";

// Settings row with an edit button
<ContentAction
  icon={SvgSettings}
  title="OpenAI"
  description="GPT"
  sizePreset="main-content"
  variant="section"
  tag={{ title: "Default", color: "blue" }}
  paddingVariant="lg"
  rightChildren={
    <Button icon={SvgSettings} prominence="tertiary" onClick={handleEdit} />
  }
/>

// No right children (padding-only wrapper for alignment)
<ContentAction
  title="Section Header"
  sizePreset="main-content"
  variant="section"
  paddingVariant="lg"
/>
```
