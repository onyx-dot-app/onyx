# CardGrid

**Import:** `import { CardGrid } from "@opal/layouts";`

A grid of cards: one column, and two once the grid is at least `@xl` (36rem) wide. The width is the grid's own (a container query), not the viewport's, so it works inside any column. Cards sit `0.5rem` apart by default; `gap` changes it.

```tsx
<CardGrid>
  <SelectCard>…</SelectCard>
  <SelectCard>…</SelectCard>
</CardGrid>
```

| Prop       | Type        | Default | Description                                              |
| ---------- | ----------- | ------- | -------------------------------------------------------- |
| `children` | `ReactNode` | —       | The grid's cards                                         |
| `gap`      | `Spacing`   | `2`     | Space between the cards, as a spacing step (`N / 4` rem) |

Use it for a set of peer cards, such as the provider cards on Language Models and Decision Models, instead of a hand-rolled grid `div`.
