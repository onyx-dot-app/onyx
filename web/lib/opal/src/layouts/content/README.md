# Content

**Import:** `import { Content, type ContentProps } from "@opal/layouts";`

An icon beside (or above) a title, with an optional description. One component: the title `font`
sets every size, and `orientation` places the icon.

## Structure

```
root            0.25rem gap inline; no gap stacked or with a secondary-* / figure-* title
├─ icon row     icon (+ moreIcon1, moreIcon2 when stacked)
└─ text         no gap
   ├─ title row title, suffix, aux icon, badge, edit pencil
   └─ description
```

## Rules

- **The title font drives everything.** An icon box is a square one title line tall (`1lh` of the
  title font), with 2px padding, so the glyph is the line height less 4px. A `secondary-*` title
  (16px line) has a 12px icon; a `heading-headline` title (36px line) has a 32px icon.
  A `figure-*` title is too small for that: its icon box has 1px padding.
- **The icon gap** is 0.25rem, except with a `secondary-*` or `figure-*` title, where the icon sits
  flush against the text. `ContentIndent`, `ContentAction`'s responsive description and
  `ReverseContent` follow the same rule.
- **The description** is always `secondary-body` in `text-03`, so a `figure-*` title (smaller than
  `secondary`) takes none.
- **`moreIcon1` / `moreIcon2`** sit in the stacked icon row, so they take a `heading-*` title font
  with `orientation="stacked"` only.
- **The extras beside the title** (`suffix`, `auxIcon`, `badge`) take a `main-ui-*`,
  `main-content-*` or `secondary-*` title font only; the types reject them with a heading, mono or
  figure font.

## Props

| Prop                   | Type                                                 | Default            | Description                                                                                                                                                                                            |
| ---------------------- | ---------------------------------------------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `font`                 | `TextFont`                                           | `"main-ui-action"` | The title's font; sets every size                                                                                                                                                                      |
| `orientation`          | `"inline" \| "stacked"`                              | `"inline"`         | Icon before the title, or above it. For an icon after the title, use [`ReverseContent`](../reverse-content/README.md)                                                                                  |
| `icon`                 | `IconFunctionComponent`                              | —                  | Leading icon                                                                                                                                                                                           |
| `enlargedIcon`         | `boolean`                                            | `false`            | Drop the icon box's 2px padding, so `icon` and `moreIcon2` are as tall as the title line. The box keeps its size. Use it where a page wants larger icons, such as the connector catalog's logos        |
| `title`                | `string \| RichStr`                                  | **(required)**     | The title                                                                                                                                                                                              |
| `description`          | `string \| RichStr`                                  | —                  | Text below the title                                                                                                                                                                                   |
| `titleMaxLines`        | `number`                                             | —                  | Clamp the title; a cut title shows in full in a tooltip                                                                                                                                                |
| `titleTooltip`         | `string \| RichStr`                                  | —                  | Shown on every hover of the title, in place of the full title                                                                                                                                          |
| `titleOverflowTooltip` | `boolean`                                            | `true`             | With `titleMaxLines`: show a cut title in full in a tooltip. Turn it off when a host wraps the content in its own tooltip                                                                              |
| `descriptionMaxLines`  | `number`                                             | —                  | Clamp the description; a cut one shows in full in a tooltip                                                                                                                                            |
| `strikethrough`        | `boolean`                                            | `false`            | Strike the title through, for an option that is switched off                                                                                                                                           |
| `suffix`               | `"optional" \| string`                               | —                  | Muted text beside the title, in the title's size and lighter weight; `"optional"` is the translated "(Optional)"                                                                                       |
| `auxIcon`              | `"info-gray" \| "info-blue" \| "warning" \| "error"` | —                  | A status icon beside the title: a 16px box with a 12px glyph at every title size, centred on the title line                                                                                            |
| `badge`                | `BadgeProps \| BadgeProps[]`                         | —                  | One badge, or a list of badges in order, beside the title                                                                                                                                              |
| `role`                 | `string`                                             | —                  | ARIA role on the title element                                                                                                                                                                         |
| `moreIcon1`            | `IconFunctionComponent`                              | —                  | Stacked only: a connector icon after the icon, in `text-03`; its box is 12px smaller than the icon box (2px padding)                                                                                   |
| `moreIcon2`            | `IconFunctionComponent`                              | —                  | Stacked only: a peer of the icon, the same size                                                                                                                                                        |
| `editable`             | `boolean`                                            | `false`            | Edit the title in place. Clicks on the title, pencil and field stay inside, so a clickable parent does not also fire.                                                                                  |
| `onTitleChange`        | `(newTitle: string) => void`                         | —                  | Called with the new, trimmed title when an edit is committed. An empty title is passed on; the caller decides whether it resets or is ignored                                                          |
| `editTooltip`          | `string`                                             | `"Edit"`           | Tooltip and accessible name of the pencil                                                                                                                                                              |
| `editButton`           | `"hover" \| "rest"`                                  | `"hover"`          | When the pencil shows: on hover of the content, or at rest too                                                                                                                                         |
| `editHandle`           | `Ref<ContentEditHandle>`                             | —                  | Starts an edit from an outside control; hides the built-in pencil                                                                                                                                      |
| `width`                | `"fit" \| "full"`                                    | `"full"`           | Shrink-wrap or fill the parent                                                                                                                                                                         |
| `color`                | `StatusColor \| "interactive"`                       | `"default"`        | The content's colour (see Colours below). A status tints the title and the icon; `"interactive"` follows the surrounding interactive surface                                                           |
| `titleColor`           | `Exclude<TextColor, "inherit">`                      | per `color`        | Overrides the title colour only; the icon keeps `color`'s, except on `"default"`, where it follows. Inside an interactive surface it holds at rest and yields to hover, pressed, selected and disabled |

## Colours

`Content` owns the status text colours (`CONTENT_STATUS_COLORS` in `content/colors.ts`); `Badge`
and `Tag` take theirs from it.

| `color`       | Title and icon                                |
| ------------- | --------------------------------------------- |
| `default`     | `text-04`; the icon follows `titleColor`      |
| `info`        | `theme-blue-05`                               |
| `success`     | `theme-green-05`                              |
| `warning`     | `status-warning-05`                           |
| `pending`     | `theme-amber-05`                              |
| `queued`      | `theme-purple-05`                             |
| `error`       | `status-error-05`                             |
| `interactive` | the surrounding interactive surface's colours |

- A muted row: `titleColor="text-03"` (the default's icon follows).
- A status icon beside a neutral title: `color="success" titleColor="text-03"`.
- The description is always `text-03`.

For a control beside the content (a button, an input), use [`ContentAction`](../content-action/README.md).

## ContentIndent

`<ContentIndent font={…}>` lines its children up under a `Content`'s title and description: it
indents them by one icon box (the title font's line height) and the icon gap (0.25rem, or none for
`secondary-*` and `figure-*` titles). Use it for a row
that continues a `Content` with an icon, such as a docs link or a detail line, instead of a
hand-written inset that drifts when `Content` changes.

```tsx
import { LinkButton } from "@opal/components";
import { Content, ContentIndent } from "@opal/layouts";
import { SvgGlobe } from "@opal/icons";

<Content font="main-ui-action" icon={SvgGlobe} title="Web search" description="Searches the web" />
<ContentIndent font="main-ui-action">
  <LinkButton href={docsUrl}>Documentation</LinkButton>
</ContentIndent>
```

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
