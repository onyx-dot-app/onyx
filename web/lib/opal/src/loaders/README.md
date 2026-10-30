# Loaders

**Import:** `import { PageLoader, CardLoader, ChatMessageLoader, DropdownLoader, LineLoader, SidebarLoader, TextLoader, IconLoader } from "@opal/loaders";`

| Loader              | Use it for                                                                                                                                      |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `PageLoader`        | A page or route that is loading: the Onyx mark with a label, centered.                                                                          |
| `CardLoader`        | A card that has not loaded: a bordered card with a shimmering icon, title and description.                                                      |
| `ChatMessageLoader` | A chat message that has not loaded: shimmering lines shaped like a user message (a bubble, at the inline end) or a reply (at the inline start). |
| `DropdownLoader`    | A select or combo box that has not loaded: the input's chrome with a shimmering icon and label.                                                 |
| `LineLoader`        | Lines of text that have not loaded: shimmering rectangles.                                                                                      |
| `SidebarLoader`     | Sidebar tabs that have not loaded: shimmering labels in a tab's footprint, or icons when folded.                                                |
| `TextLoader`        | Real text for a status still in progress: the text itself shimmers.                                                                             |
| `IconLoader`        | An inline spinner, e.g. beside a label or in a row.                                                                                             |

`LineLoader`, `CardLoader`, `DropdownLoader` and `TextLoader` share one wave: 40% of the length but at least 40px, a 2s crossing whatever the length, then a 1s pause. Only the colours differ. The shimmer and the spinner hold still under `prefers-reduced-motion`. `CardLoader`, `DropdownLoader`, `LineLoader`, `SidebarLoader` and `IconLoader` announce themselves to screen readers with the Opal loading label; `TextLoader` shows real text, so it says nothing extra.

## CardLoader

```tsx
<CardLoader />
<CardLoader descriptionLines={2} />
<CardLoader border="dashed" rounding={3} color="background-tint-00" />
```

Props: `descriptionLines` (default `1`), plus the plain-mode `Card` props it forwards (`padding`, `rounding`, `color`, `border`, `borderColor`, `shadow`, `disabled`, `ref`, `data-*`). `children` and `expandable` are not accepted: the loader fills the body and is never expandable. Unset, the card is transparent and solid-bordered, with `rounding={4}` and `padding={4}`. The inside imitates a `ContentAction` row; it is not a `Content`.

## ChatMessageLoader

```tsx
<ChatMessageLoader orientation="end" />    // the user's message: a bubble
<ChatMessageLoader orientation="start" />  // the reply: plain lines
```

Props:

- `orientation` (`"start" | "end"`, default `"start"`), on the inline sides, so it mirrors in right-to-left text. `"end"` is a bubble shaped and tinted like a user message (`tint-02`); its bars are a step darker (`tint-03`) so they stay visible on it. `"start"` is plain lines.
- `lines`: lines of text, at least 1. Unset, a random count: 1 to 3 for `"end"`, 1 to 5 for `"start"`.
- `lastLineWidth`: the last line's width, as on `LineLoader`. Unset, a random width.
- `bubbleWidth` (`"end"` only): the bubble's share of the column, `"1/3" | "1/2" | "2/3"`. Unset, a random width.

The random shape is seeded from the instance's `useId`, so each loader has its own shape, the same on the server and the client and on every render. Stack several, alternating, to stand in for a conversation. Each loader is hidden from assistive technology (`aria-hidden`), so a stack does not announce "loading" once per line; give the stack one `role="status"` with a label.

## DropdownLoader

```tsx
<DropdownLoader />
```

No props. The input's resting chrome (border, background, radius, padding) holding a shimmering icon and label and a static chevron icon, laid out like a select's trigger, so it is as tall as the input; it fills its column, so in an `InputHorizontal` give the row `fillInput`.

## LineLoader

```tsx
<LineLoader />
<LineLoader lines={3} width="2/3" />
```

Props: `lines` (default `1`), `width` of the last line (`"full" | "3/4" | "2/3" | "1/2" | "1/3" | "1/4"`, default `"full"`), `height` of each line as a `LineHeight` step (`3 | 4 | 5 | 6 | 7 | 8 | 9 | 12`, default `5`, 20px). Each bar keeps its own height and sits centred in its line, so the loader is as tall as what it replaces: `height={9}` (36px) stands in for a select.

## SidebarLoader

```tsx
<SidebarLoader count={3} />   // three tabs, e.g. a section that is loading
<SidebarLoader folded />      // the folded sidebar's icon-only tab
```

Props: `count` (default `1`), the number of tabs; `folded` (default `false`), a shimmering icon in place of each label. Each tab has a sidebar tab's footprint, so the real tabs replace it without a shift. The labels cycle through three widths, so a stack reads as a list. The stack announces itself once, with the Opal loading label.

## TextLoader

```tsx
<TextLoader>Thinking…</TextLoader>
<TextLoader font="main-ui-body">Indexing documents…</TextLoader>
```

Props: `children` (plain `string`; markdown is not accepted), `font` (`TextFont`, default `"main-ui-action"`). The text rests at `text-02` and the wave peaks at `text-04`.

The wave is 40% of the text's length, never narrower than 40px. Its rate scales with the length, so it crosses any text in 2s, with a 1s pause between waves; on wrapped text it runs along each line in reading order. Those four values are constants at the top of `text-loader/components.tsx`.

## IconLoader

The static `SvgLoader` ring (a 3/4 circle in `currentColor`), spun, at 16px by default. It takes the same props as any icon, so use it two ways:

```tsx
<IconLoader />                                   // on its own, 16px
<IconLoader size={24} className="text-text-03" />
<Button icon={isSaving ? IconLoader : SvgCheck}>Save</Button> // the Button sets the size
```

Colour follows `currentColor`. There is no separate spinning icon: `SvgLoader` is static and unsized, and `IconLoader` is what spins and sizes it.

## PageLoader

See `page-loader/README.md`.
