# Text

**Import:** `import { Text, type TextProps, type TextFont, type TextColor } from "@opal/components";`

A styled text component with string-enum props for font preset and color selection. Supports
inline markdown rendering via `RichStr` — pass `markdown("*bold* text")` as children to enable.

## Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `font` | `TextFont` | `"main-ui-body"` | Font preset (size, weight, line-height) |
| `color` | `TextColor` | `"text-04"` | Text color |
| `as` | `"p" \| "span" \| "li" \| "h1" \| "h2" \| "h3"` | `"span"` | HTML tag to render |
| `nowrap` | `boolean` | `false` | Prevent text wrapping |

### `TextFont`

| Value | Size | Weight | Line-height |
|---|---|---|---|
| `"heading-h1"` | 48px | 600 | 64px |
| `"heading-h2"` | 24px | 600 | 36px |
| `"heading-h3"` | 18px | 600 | 28px |
| `"heading-h3-muted"` | 18px | 500 | 28px |
| `"main-content-body"` | 16px | 450 | 24px |
| `"main-content-muted"` | 16px | 400 | 24px |
| `"main-content-emphasis"` | 16px | 700 | 24px |
| `"main-content-mono"` | 16px | 400 | 23px |
| `"main-ui-body"` | 14px | 500 | 20px |
| `"main-ui-muted"` | 14px | 400 | 20px |
| `"main-ui-action"` | 14px | 600 | 20px |
| `"main-ui-mono"` | 14px | 400 | 20px |
| `"secondary-body"` | 12px | 400 | 18px |
| `"secondary-action"` | 12px | 600 | 18px |
| `"secondary-mono"` | 12px | 400 | 18px |
| `"figure-small-label"` | 10px | 600 | 14px |
| `"figure-small-value"` | 10px | 400 | 14px |
| `"figure-keystroke"` | 11px | 400 | 16px |

### `TextColor`

`"text-01" | "text-02" | "text-03" | "text-04" | "text-05" | "text-inverted-01" | "text-inverted-02" | "text-inverted-03" | "text-inverted-04" | "text-inverted-05" | "text-light-03" | "text-light-05" | "text-dark-03" | "text-dark-05"`

## Usage Examples

```tsx
import { Text } from "@opal/components";

// Basic
<Text font="main-ui-body" color="text-03">
  Hello world
</Text>

// Heading
<Text font="heading-h2" color="text-05" as="h2">
  Page Title
</Text>

// Inverted (for dark backgrounds)
<Text font="main-ui-body" color="text-inverted-05">
  Light text on dark
</Text>

// As paragraph
<Text font="main-content-body" color="text-03" as="p">
  A full paragraph of text.
</Text>
```

## Inline Markdown via `RichStr`

Inline markdown is opt-in via the `markdown()` function, which returns a `RichStr`. When `Text`
receives a `RichStr` as children, it parses the inner string as inline markdown. Plain strings
and JSX children are rendered as-is — no parsing, no surprises.

```tsx
import { Text } from "@opal/components";
import { markdown } from "@opal/types";

// Inline markdown — bold, italic, links, code, strikethrough
<Text font="main-ui-body" color="text-05">
  {markdown("*Hello*, **world**! Visit [Onyx](https://onyx.app) and run `onyx start`.")}
</Text>

// Plain string — no markdown parsing
<Text font="main-ui-body" color="text-03">
  This *stays* as-is, no formatting applied.
</Text>
```

Supported syntax: `**bold**`, `*italic*`, `` `code` ``, `[link](url)`, `~~strikethrough~~`.

Markdown rendering uses `react-markdown` internally, restricted to inline elements only.
`http(s)` links open in a new tab; `mailto:` and `tel:` links open natively. Inline code
inherits the parent font size and switches to the monospace family.

**Note:** This is inline-only markdown. Multi-paragraph content (`"Hello\n\nWorld"`) will
collapse into a single run of text since paragraph wrappers are stripped. For block-level
markdown, use `MinimalMarkdown` instead.

### Using `RichStr` in component props

Components that want to support optional markdown in their text props should accept
`string | RichStr`:

```tsx
import type { RichStr } from "@opal/types";

interface MyComponentProps {
  title: string | RichStr;
  description?: string | RichStr;
}
```

This avoids API coloring — no `markdown` boolean needs to be threaded through intermediate
components. The decision to use markdown lives at the call site.

## Compatibility

`@/refresh-components/texts/Text` is an independent legacy component that implements the same
font/color presets via a boolean-flag API. It is **not** a wrapper around this component. New
code should import directly from `@opal/components`.
