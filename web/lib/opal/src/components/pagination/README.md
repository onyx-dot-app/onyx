# Pagination

**Import:** `import { Pagination, type PaginationProps } from "@opal/components";`

Page navigation with three display variants and prev/next arrow controls.

## Variants

### `"list"` (default)

Numbered page buttons with ellipsis truncation for large page counts.

```tsx
<Pagination currentPage={3} totalPages={10} onChange={setPage} />
```

### `"simple"`

Compact `currentPage/totalPages` display with prev/next arrows. Can be reduced to just arrows via `hidePages`.

```tsx
// With summary (default)
<Pagination variant="simple" currentPage={1} totalPages={5} onChange={setPage} />

// Arrows only
<Pagination variant="simple" currentPage={1} totalPages={5} onChange={setPage} hidePages />

// With units
<Pagination variant="simple" currentPage={1} totalPages={5} onChange={setPage} units="pages" />
```

### `"count"`

Item-count display (`X~Y of Z`) with prev/next arrows. Designed for table footers.

```tsx
// Basic
<Pagination
  variant="count"
  pageSize={10}
  totalItems={95}
  currentPage={2}
  totalPages={10}
  onChange={setPage}
/>

// With units
<Pagination
  variant="count"
  pageSize={10}
  totalItems={95}
  currentPage={2}
  totalPages={10}
  onChange={setPage}
  units="items"
/>
```

## Props (shared)

| Prop | Type | Default | Description |
|---|---|---|---|
| `variant` | `"list" \| "simple" \| "count"` | `"list"` | Display variant |
| `currentPage` | `number` | **(required)** | 1-based current page number |
| `totalPages` | `number` | **(required)** | Total number of pages |
| `onChange` | `(page: number) => void` | — | Called when the page changes |
| `size` | `PaginationSize` | `"lg"` | Button and text sizing |

## Props (variant-specific)

### `"simple"`

| Prop | Type | Default | Description |
|---|---|---|---|
| `hidePages` | `boolean` | `false` | Hides the `currentPage/totalPages` text between arrows |
| `units` | `string` | — | Label after the summary (e.g. `"pages"`), always 4px spacing |

### `"count"`

| Prop | Type | Default | Description |
|---|---|---|---|
| `pageSize` | `number` | **(required)** | Items per page (for range calculation) |
| `totalItems` | `number` | **(required)** | Total item count |
| `hidePages` | `boolean` | `false` | Hides the current page number between arrows |
| `units` | `string` | — | Label after the total (e.g. `"items"`), always 4px spacing |

### `PaginationSize`

`"lg" | "md" | "sm"`
