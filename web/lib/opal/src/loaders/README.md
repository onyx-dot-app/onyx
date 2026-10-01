# Loaders

**Import:** `import { PageLoader, CardLoader, LineLoader, TextLoader, IconLoader } from "@opal/loaders";`

| Loader | Use it for |
| ------ | ---------- |
| `PageLoader` | A page or route that is loading: the Onyx mark with a label, centered. |
| `CardLoader` | A card that has not loaded: a bordered card with a shimmering icon, title and description. |
| `LineLoader` | Lines of text that have not loaded: shimmering rectangles. |
| `TextLoader` | Real text for a status still in progress: the text itself shimmers. |
| `IconLoader` | An inline spinner, e.g. beside a label or in a row. |

`LineLoader`, `CardLoader` and `TextLoader` share one wave: 40% of the length but at least 40px, a 2s crossing whatever the length, then a 1s pause. Only the colours differ. The shimmer and the spinner hold still under `prefers-reduced-motion`. `CardLoader`, `LineLoader` and `IconLoader` announce themselves to screen readers with the Opal loading label; `TextLoader` shows real text, so it says nothing extra.

## CardLoader

```tsx
<CardLoader />
<CardLoader descriptionLines={2} />
<CardLoader border="dashed" rounding={3} color="transparent" />
```

Props: `descriptionLines` (default `1`), plus every plain-mode `Card` prop (`padding`, `rounding`, `color`, `border`, `borderColor`, `shadow`, `disabled`, `ref`, `data-*`). Unset, the card is solid-bordered with `rounding={4}` and `padding={4}`. The inside imitates a `ContentAction` row; it is not a `Content`.

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
