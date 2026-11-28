# CardGrid

**Import:** `import { CardGrid } from "@opal/layouts";`

A grid of cards. By default it has one column, and two once the grid is at least `@xl` (36rem) wide; `columns="two-to-three"` gives two columns, and three once the grid is 24rem wide. `columns="one-to-four"` gives one column, two at 18rem, three at 30rem and four at 44rem. The width is the grid's own (a container query), not the viewport's, so it works inside any column. Cards sit `0.5rem` apart by default; `gap` changes it.

```tsx
<CardGrid>
  <SelectCard>…</SelectCard>
  <SelectCard>…</SelectCard>
</CardGrid>
```

| Prop       | Type                                              | Default        | Description                                                                                                                                                                                           |
| ---------- | ------------------------------------------------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `children` | `ReactNode`                                       | —              | The grid's cards                                                                                                                                                                                      |
| `gap`      | `Spacing`                                         | `2`            | Space between the cards, as a spacing step (`N / 4` rem)                                                                                                                                              |
| `columns`  | `"one-to-two" \| "two-to-three" \| "one-to-four"` | `"one-to-two"` | `"two-to-three"`: two columns, three once the grid is 24rem wide, for small tiles such as output thumbnails. `"one-to-four"`: one to four columns (18rem, 30rem, 44rem steps), for a catalog of tiles |

Use it for a set of peer cards, such as the provider cards on Language Models and Decision Models, instead of a hand-rolled grid `div`.
