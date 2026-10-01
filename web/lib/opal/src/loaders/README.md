# Loaders

**Import:** `import { PageLoader, CardLoader, LineLoader, TextLoader, IconLoader } from "@opal/loaders";`

| Loader | Use it for |
| ------ | ---------- |
| `PageLoader` | A page or route that is loading: the Onyx mark with a label, centered. |
| `CardLoader` | A card that has not loaded: a bordered card with a shimmering icon, title and description. |
| `LineLoader` | Lines of text that have not loaded: shimmering rectangles. |
| `TextLoader` | Real text for a status still in progress: the text itself shimmers. |
| `IconLoader` | An inline spinner, e.g. beside a label or in a row. |

The shimmer and the spinner hold still under `prefers-reduced-motion`. `CardLoader`, `LineLoader` and `IconLoader` announce themselves to screen readers with the Opal loading label; `TextLoader` shows real text, so it says nothing extra.

## CardLoader

```tsx
<CardLoader />
<CardLoader descriptionLines={2} />
```

Props: `descriptionLines` (default `1`).

## LineLoader

```tsx
<LineLoader />
<LineLoader lines={3} width="2/3" />
```

Props: `lines` (default `1`), `width` of the last line (`"full" | "3/4" | "2/3" | "1/2" | "1/3" | "1/4"`, default `"full"`).

## TextLoader

```tsx
<TextLoader>Thinking…</TextLoader>
<TextLoader font="main-ui-body">Indexing documents…</TextLoader>
```

Props: `children` (`string | RichStr`), `font` (`TextFont`, default `"main-ui-action"`). The text rests at `text-02` and the wave peaks at `text-04`.

The wave is 40px wide (half the text, on text under 80px) and moves at 60px/s on any length of text, with a 1s pause between waves; on wrapped text it runs along each line in reading order. Those three values are constants at the top of `text-loader/components.tsx`.

## IconLoader

`SvgSimpleLoader` at a set size. The icon is unsized; `IconLoader` decides the size.

```tsx
<IconLoader />
<IconLoader size={24} color="text-03" />
```

Props: `size` (px, default `16`), `color` (`LoaderColor`, default `"inherit"`, which follows the surrounding text color).

## PageLoader

See `page-loader/README.md`.
