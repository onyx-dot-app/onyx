# Content

**Import:** `import { Content, type ContentProps } from "@opal/layouts";`

An icon beside (or above) a title, with an optional description. One component: the title `font`
sets every size, and `orientation` places the icon.

## Structure

```
root            0.25rem gap inline; no gap stacked
├─ icon row     icon (+ moreIcon1, moreIcon2 when stacked)
└─ text         no gap
   ├─ title row title, suffix, aux icon, badge, edit pencil
   └─ description
```

## Rules

- **The title font drives everything.** An icon box is a square one title line tall (`1lh` of the
  title font), with 2px padding, so the glyph is the line height less 4px. A `secondary-*` title
  (16px line) has a 12px icon; a `heading-headline` title (36px line) has a 32px icon.
- **The description** is always `secondary-body` in `text-03`, so a `figure-*` title (smaller than
  `secondary`) takes none.
- **`moreIcon1` / `moreIcon2`** sit in the stacked icon row, so they take a `heading-*` title font
  with `orientation="stacked"` only.
- **The extras beside the title** (`suffix`, `auxIcon`, `badge`) take a `main-ui-*`,
  `main-content-*` or `secondary-*` title font only; the types reject them with a heading, mono or
  figure font.

## Props

| Prop                  | Type                                       | Default            | Description                                                                                         |
| --------------------- | ------------------------------------------ | ------------------ | --------------------------------------------------------------------------------------------------- |
| `font`                | `TextFont`                                 | `"main-ui-action"` | The title's font; sets every size                                                                   |
| `orientation`         | `"inline" \| "stacked"`                  | `"inline"`         | Icon before the title, or above it. For an icon after the title, use [`ReverseContent`](../reverse-content/README.md) |
| `icon`                | `IconFunctionComponent`                    | —                  | Leading icon                                                                                        |
| `enlargedIcon`        | `boolean`                                  | `false`            | Drop the icon box's 2px padding, so `icon` and `moreIcon2` are as tall as the title line. The box keeps its size. Use it where a page wants larger icons, such as the connector catalog's logos |
| `title`               | `string \| RichStr`                        | **(required)**     | The title                                                                                           |
| `description`         | `string \| RichStr`                        | —                  | Text below the title                                                                                |
| `titleMaxLines`       | `number`                                   | —                  | Clamp the title; a cut title shows in full in a tooltip                                             |
| `descriptionMaxLines` | `number`                                   | —                  | Clamp the description; a cut one shows in full in a tooltip                                         |
| `strikethrough`       | `boolean`                                  | `false`            | Strike the title through, for an option that is switched off                                        |
| `suffix`              | `"optional" \| string`                     | —                  | Muted text beside the title, in the title's size and lighter weight; `"optional"` is the translated "(Optional)" |
| `auxIcon`             | `"info-gray" \| "info-blue" \| "warning" \| "error"` | —        | A status icon beside the title: a 16px box with a 12px glyph at every title size, centred on the title line |
| `badge`               | `BadgeProps & { tooltip?: string }`        | —                  | A badge beside the title                                                                            |
| `role`                | `string`                                   | —                  | ARIA role on the title element                                                                      |
| `moreIcon1`           | `IconFunctionComponent`                    | —                  | Stacked only: a connector icon after the icon, in `text-03`; its box is 12px smaller than the icon box (2px padding) |
| `moreIcon2`           | `IconFunctionComponent`                    | —                  | Stacked only: a peer of the icon, the same size                                                     |
| `editable`            | `boolean`                                  | `false`            | Edit the title in place. Clicks on the title, pencil and field stay inside, so a clickable parent does not also fire. An empty edit keeps the old title |
| `onTitleChange`       | `(newTitle: string) => void`               | —                  | Called with the new title when an edit is committed                                                 |
| `editTooltip`         | `string`                                   | `"Edit"`           | Tooltip and accessible name of the pencil                                                           |
| `editButton`          | `"hover" \| "rest"`                        | `"hover"`          | When the pencil shows: on hover of the content, or at rest too                                      |
| `editHandle`          | `Ref<ContentEditHandle>`                   | —                  | Starts an edit from an outside control; hides the built-in pencil                                   |
| `width`               | `"fit" \| "full"`                          | `"full"`           | Shrink-wrap or fill the parent                                                                      |
| `color`               | `ColorTypes`                               | `"default"`        | Icon and title colour pair. `"success"` / `"warning"` / `"danger"` colour only the icon and leave the text at `text-03`; `"interactive"` follows the surrounding interactive surface |
| `titleColor`          | `Exclude<TextColor, "inherit">`            | per `color`        | Overrides the title colour only. Inside an interactive surface it holds at rest and yields to hover, pressed, selected and disabled |

For a control beside the content (a button, an input), use [`ContentAction`](../content-action/README.md).

## Usage

```tsx
import { Content } from "@opal/layouts";
import SvgSearch from "@opal/icons/search";

// A page heading, icon on top
<Content
  font="heading-headline"
  orientation="stacked"
  icon={SvgSearch}
  title="Agent Settings"
  description="Configure your agent's behavior"
/>

// A row label
<Content
  font="main-ui-action"
  icon={SvgSearch}
  title="Instructions"
  description="Agent system prompt"
  suffix="optional"
/>

// Editable title
<Content
  font="heading-section"
  icon={SvgSearch}
  title="My Agent"
  editable
  onTitleChange={(newTitle) => save(newTitle)}
/>
```
