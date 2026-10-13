# Fold

**Import:** `import { Fold } from "@opal/components";`

Content that opens and closes by animating its height, with a fade. It paints
nothing of its own (no border, background or padding), so the content stays
part of whatever surrounds it: rows folding inside a card stay in the card.

## Props

| Prop          | Type                     | Default | Description                                                                                                             |
| ------------- | ------------------------ | ------- | ----------------------------------------------------------------------------------------------------------------------- |
| `open`        | `boolean`                | —       | Whether the fold is open                                                                                                |
| `keepMounted` | `boolean`                | `false` | Keep the children while closed (e.g. to keep form state)                                                                |
| `id`          | `string`                 | —       | For a control that points at the fold with `aria-controls`                                                              |
| `frame`       | `(content) => ReactNode` | —       | Wraps the content in a frame (e.g. a bordered box) that grows with the height and stays visible; only the content fades |
| `children`    | `ReactNode`              | —       | The folded content                                                                                                      |

## Behaviour

- A CSS grid row moves between `0fr` and `1fr`; no height is measured. Opening
  expands the height fully (150ms), then fades the content in (100ms). Closing
  fades it out first, then collapses. Reduced motion turns the animation off.
- Closed, the fold takes no space. In a flex parent with a `gap`, put the
  spacing inside the fold's content, or the gap stays around the closed fold.
- Children stay mounted through the closing animation, then drop, so a closed
  fold holds nothing, unless `keepMounted`.
- The root carries `data-open` (open now), `data-visible` (open or still
  closing, so it has height) and `data-mounted` (its children are mounted,
  which `keepMounted` makes always true). Style on `data-visible` for anything
  that must follow the height.
- While closed or closing, the fold is `inert` and `aria-hidden`.
- `CardFold` (`Card` and `SelectCard`) passes its bordered body as the `frame`.
- `Card`, `SelectCard`, `Collapsible`, `Divider` (foldable) and `MessageCard`
  (its bottom section) all fold with it.

## Usage

```tsx
<Fold open={expanded}>
  <CheckList />
</Fold>
```
