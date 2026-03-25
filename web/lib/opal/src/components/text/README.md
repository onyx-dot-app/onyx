# Text

**Import:** `import { Text, type TextProps, type TextFont, type TextColor } from "@opal/components";`

A styled text component with string-enum props for font preset and color selection, plus opt-in inline markdown rendering.

## Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `font` | `TextFont` | `"main-ui-body"` | Font preset (size, weight, line-height) |
| `color` | `TextColor` | `"text-05"` | Text color |
| `inverted` | `boolean` | `false` | Use inverted color palette |
| `as` | `"p" \| "span" \| "li"` | `"span"` | HTML tag to render |
| `nowrap` | `boolean` | `false` | Prevent text wrapping |
| `markdown` | `boolean` | `false` | Parse children as inline markdown |

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

`"text-01" | "text-02" | "text-03" | "text-04" | "text-05" | "text-light-03" | "text-light-05" | "text-dark-03" | "text-dark-05"`

When `inverted` is true, colors map to their `text-inverted-*` counterparts (except `text-light-*` and `text-dark-*` which remain unchanged).

## Usage Examples

```tsx
import { Text } from "@opal/components";

// Basic
<Text font="main-ui-body" color="text-03">
  Hello world
</Text>

// Heading
<Text font="heading-h2" color="text-05">
  Page Title
</Text>

// Inverted (for dark backgrounds)
<Text font="main-ui-body" color="text-05" inverted>
  Light text on dark
</Text>

// As paragraph
<Text font="main-content-body" color="text-03" as="p">
  A full paragraph of text.
</Text>
```

## Inline Markdown

When `markdown` is true and `children` is a string, the text is parsed as inline markdown. Supported syntax: `**bold**`, `*italic*`, `` `code` ``, `[link](url)`, `~~strikethrough~~`.

```tsx
<Text font="main-ui-body" color="text-05" markdown>
  {"*Hello*, **world**! Visit [Onyx](https://onyx.app) and run `onyx start`."}
</Text>
```

Markdown rendering uses `react-markdown` internally, restricted to inline elements only. Links open in a new tab and inherit the surrounding text color.

## Compatibility

A backward-compatible wrapper exists at `@/refresh-components/texts/Text` that maps the legacy boolean-flag API to this component. New code should import directly from `@opal/components`.
