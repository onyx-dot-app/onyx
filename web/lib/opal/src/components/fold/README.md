# Fold

**Import:** `import { Fold } from "@opal/components";`

Content that opens and closes by animating its height, with a fade. It paints
nothing of its own (no border, background or padding), so the content stays
part of whatever surrounds it: rows folding inside a card stay in the card.

## Props

| Prop          | Type        | Default | Description                                                |
| ------------- | ----------- | ------- | ---------------------------------------------------------- |
| `open`        | `boolean`   | —       | Whether the fold is open                                   |
| `keepMounted` | `boolean`   | `false` | Keep the children while closed (e.g. to keep form state)   |
| `id`          | `string`    | —       | For a control that points at the fold with `aria-controls` |
| `children`    | `ReactNode` | —       | The folded content                                         |

## Behaviour

- A CSS grid row moves between `0fr` and `1fr` with an opacity fade over
  200ms; no height is measured. Reduced motion turns the animation off.
- Closed, the fold takes no space. In a flex parent with a `gap`, put the
  spacing inside the fold's content, or the gap stays around the closed fold.
- Children stay mounted through the closing animation, then drop, so a closed
  fold holds nothing, unless `keepMounted`.
- While closed or closing, the fold is `inert` and `aria-hidden`.
- `Card`, `SelectCard`, `Collapsible`, `Divider` (foldable) and `MessageCard`
  (its bottom section) all fold with it.

## Usage

```tsx
<Fold open={expanded}>
  <CheckList />
</Fold>
```
