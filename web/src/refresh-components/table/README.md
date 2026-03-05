# DataTable

Config-driven table built on [TanStack Table](https://tanstack.com/table). Handles column sizing (weight-based proportional distribution), drag-and-drop row reordering, pagination, row selection, column visibility, and sorting out of the box.

## Quick Start

```tsx
import DataTable from "@/refresh-components/table/DataTable";
import { createTableColumns } from "@/refresh-components/table/columns";

interface Person {
  name: string;
  email: string;
  role: string;
}

// Define columns at module scope (stable reference, no re-renders)
const tc = createTableColumns<Person>();
const columns = [
  tc.qualifier(),
  tc.column("name", { header: "Name", weight: 30, minWidth: 120 }),
  tc.column("email", { header: "Email", weight: 40, minWidth: 150 }),
  tc.column("role", { header: "Role", weight: 30, minWidth: 80 }),
  tc.actions(),
];

function PeopleTable({ data }: { data: Person[] }) {
  return (
    <DataTable
      data={data}
      columns={columns}
      pageSize={10}
      footer={{ mode: "selection" }}
    />
  );
}
```

## Column Builder API

`createTableColumns<TData>()` returns a typed builder with four methods. Each returns an `OnyxColumnDef<TData>` that you pass to the `columns` prop.

### `tc.qualifier(config?)`

Leading column for avatars, icons, images, or checkboxes.

| Option | Type | Default | Description |
|---|---|---|---|
| `content` | `"simple" \| "icon" \| "image" \| "avatar-icon" \| "avatar-user"` | `"simple"` | Body row content type |
| `headerContentType` | same as `content` | `"simple"` | Header row content type |
| `getInitials` | `(row: TData) => string` | - | Extract initials (for `"avatar-user"`) |
| `getIcon` | `(row: TData) => IconFunctionComponent` | - | Extract icon (for `"icon"` / `"avatar-icon"`) |
| `getImageSrc` | `(row: TData) => string` | - | Extract image src (for `"image"`) |
| `selectable` | `boolean` | `true` | Show selection checkboxes |
| `header` | `boolean` | `true` | Render qualifier content in the header |

Width is fixed: 56px at `"regular"` size, 40px at `"small"`.

```ts
tc.qualifier({
  content: "avatar-user",
  getInitials: (row) => row.initials,
})
```

### `tc.column(accessor, config)`

Data column with sorting, resizing, and hiding. The `accessor` is a type-safe deep key into `TData`.

| Option | Type | Default | Description |
|---|---|---|---|
| `header` | `string` | **required** | Column header label |
| `cell` | `(value: TValue, row: TData) => ReactNode` | renders value as string | Custom cell renderer |
| `enableSorting` | `boolean` | `true` | Allow sorting |
| `enableResizing` | `boolean` | `true` | Allow column resize |
| `enableHiding` | `boolean` | `true` | Allow hiding via actions popover |
| `icon` | `(sorted: SortDirection) => IconFunctionComponent` | - | Override the sort indicator icon |
| `weight` | `number` | `20` | Proportional width weight |
| `minWidth` | `number` | `50` | Minimum width in pixels |

```ts
tc.column("email", {
  header: "Email",
  weight: 28,
  minWidth: 150,
  cell: (value) => <Content sizePreset="main-ui" variant="body" title={value} prominence="muted" />,
})
```

### `tc.displayColumn(config)`

Non-accessor column for custom content (e.g. computed values, action buttons per row).

| Option | Type | Default | Description |
|---|---|---|---|
| `id` | `string` | **required** | Unique column ID |
| `header` | `string` | - | Optional header label |
| `cell` | `(row: TData) => ReactNode` | **required** | Cell renderer |
| `width` | `ColumnWidth` | **required** | `{ weight, minWidth? }` or `{ fixed }` |
| `enableHiding` | `boolean` | `true` | Allow hiding |

```ts
tc.displayColumn({
  id: "fullName",
  header: "Full Name",
  cell: (row) => `${row.firstName} ${row.lastName}`,
  width: { weight: 25, minWidth: 100 },
})
```

### `tc.actions(config?)`

Fixed-width column rendered at the trailing edge. Houses column visibility and sorting popovers in the header.

| Option | Type | Default | Description |
|---|---|---|---|
| `showColumnVisibility` | `boolean` | `true` | Show the column visibility popover |
| `showSorting` | `boolean` | `true` | Show the sorting popover |
| `sortingFooterText` | `string` | - | Footer text inside the sorting popover |
| `cell` | `(row: TData) => ReactNode` | - | Row-level cell renderer for action buttons |

Width is fixed: 88px at `"regular"`, 20px at `"small"`.

```ts
tc.actions({
  sortingFooterText: "Everyone will see agents in this order.",
})
```

Row-level actions — the `cell` callback receives the row data and renders content in each body row. Clicks inside the cell automatically call `stopPropagation`, so they won't trigger row selection.

```tsx
tc.actions({
  cell: (row) => (
    <div className="flex gap-x-1">
      <IconButton icon={SvgPencil} onClick={() => openEdit(row.id)} />
      <IconButton icon={SvgTrash} onClick={() => confirmDelete(row.id)} />
    </div>
  ),
})
```

## DataTable Props

`DataTableProps<TData>`:

| Prop | Type | Default | Description |
|---|---|---|---|
| `data` | `TData[]` | **required** | Row data |
| `columns` | `OnyxColumnDef<TData>[]` | **required** | Columns from `createTableColumns()` |
| `pageSize` | `number` | `10` (with footer) or `data.length` (without) | Rows per page. `Infinity` disables pagination |
| `initialSorting` | `SortingState` | `[]` | TanStack sorting state |
| `initialColumnVisibility` | `VisibilityState` | `{}` | Map of column ID to `false` to hide initially |
| `draggable` | `DataTableDraggableConfig<TData>` | - | Enable drag-and-drop (see below) |
| `footer` | `DataTableFooterConfig` | - | Footer mode (see below) |
| `size` | `"regular" \| "small"` | `"regular"` | Table density variant |
| `onRowClick` | `(row: TData) => void` | toggles selection | Called on row click, replaces default selection toggle |
| `height` | `number \| string` | - | Max height for scrollable body (header stays pinned). `300` or `"50vh"` |
| `headerBackground` | `string` | - | CSS color for the sticky header (prevents content showing through) |
| `searchTerm` | `string` | - | Search term for client-side global text filtering (case-insensitive match across all accessor columns) |
| `serverSide` | `ServerSideConfig` | - | Enable server-side mode for manual pagination, sorting, and filtering ([see below](#server-side-mode)) |

## Footer Config

The `footer` prop accepts a discriminated union on `mode`.

### Selection mode

For tables with selectable rows. Shows a selection message + count pagination.

```ts
footer={{
  mode: "selection",
  multiSelect: true,        // default true
  onView: () => { ... },    // optional "View" button
  onClear: () => { ... },   // optional "Clear" button (falls back to default clearSelection)
}}
```

### Summary mode

For read-only tables. Shows "Showing X~Y of Z" + list pagination.

```ts
footer={{ mode: "summary" }}
```

## Draggable Config

Enable drag-and-drop row reordering. DnD is automatically disabled when column sorting is active.

```ts
<DataTable
  data={items}
  columns={columns}
  draggable={{
    getRowId: (row) => row.id,
    onReorder: (ids, changedOrders) => {
      // ids: new ordered array of all row IDs
      // changedOrders: { [id]: newIndex } for rows that moved
      setItems(ids.map((id) => items.find((r) => r.id === id)!));
    },
  }}
/>
```

| Option | Type | Description |
|---|---|---|
| `getRowId` | `(row: TData) => string` | Extract a unique string ID from each row |
| `onReorder` | `(ids: string[], changedOrders: Record<string, number>) => void \| Promise<void>` | Called after a successful reorder |

## Server-Side Mode

Pass the `serverSide` prop to switch from client-side to server-side pagination, sorting, and filtering. In this mode `data` should contain **only the current page slice** — TanStack operates with `manualPagination`, `manualSorting`, and `manualFiltering` enabled. Drag-and-drop is automatically disabled.

### `ServerSideConfig`

| Prop | Type | Description |
|---|---|---|
| `totalItems` | `number` | Total row count from the server, used to compute page count |
| `isLoading` | `boolean` | Shows a loading overlay (opacity + pointer-events-none) while data is being fetched |
| `onSortingChange` | `(sorting: SortingState) => void` | Fired when the user clicks a column header |
| `onPaginationChange` | `(pageIndex: number, pageSize: number) => void` | Fired on page navigation and on automatic resets from sort/search changes |
| `onSearchTermChange` | `(searchTerm: string) => void` | Fired when the `searchTerm` prop changes |

### Callback contract

The callbacks fire in a predictable order:

- **Sort change** — `onSortingChange` fires first, then the page resets to 0 and `onPaginationChange(0, pageSize)` fires.
- **Page navigation** — only `onPaginationChange` fires.
- **Search change** — `onSearchTermChange` fires, and the page resets to 0. `onPaginationChange` only fires if the page was actually on a non-zero page. When already on page 0, `searchTerm` drives the re-fetch independently (e.g. via your SWR key) — no `onPaginationChange` is needed.

Your data-fetching layer should include `searchTerm` in its fetch dependencies (e.g. SWR key) so that search changes trigger re-fetches regardless of pagination state.

### Full example

```tsx
import { useState } from "react";
import useSWR from "swr";
import type { SortingState } from "@tanstack/react-table";
import DataTable from "@/refresh-components/table/DataTable";
import { createTableColumns } from "@/refresh-components/table/columns";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";

interface User {
  id: string;
  name: string;
  email: string;
}

const tc = createTableColumns<User>();
const columns = [
  tc.qualifier(),
  tc.column("name", { header: "Name", weight: 40, minWidth: 120 }),
  tc.column("email", { header: "Email", weight: 60, minWidth: 150 }),
  tc.actions(),
];

function UsersTable() {
  const [searchTerm, setSearchTerm] = useState("");
  const [sorting, setSorting] = useState<SortingState>([]);
  const [pageIndex, setPageIndex] = useState(0);
  const [pageSize, setPageSize] = useState(10);

  const { data: response, isLoading } = useSWR(
    ["/api/users", sorting, pageIndex, pageSize, searchTerm],
    ([url, sorting, pageIndex, pageSize, searchTerm]) =>
      fetch(
        `${url}?` +
          new URLSearchParams({
            page: String(pageIndex),
            size: String(pageSize),
            search: searchTerm,
            ...(sorting[0] && {
              sortBy: sorting[0].id,
              sortDir: sorting[0].desc ? "desc" : "asc",
            }),
          })
      ).then((r) => r.json())
  );

  return (
    <div className="space-y-4">
      <InputTypeIn
        value={searchTerm}
        onChange={(e) => setSearchTerm(e.target.value)}
        placeholder="Search users..."
      />
      <DataTable
        data={response?.items ?? []}
        columns={columns}
        getRowId={(row) => row.id}
        searchTerm={searchTerm}
        pageSize={pageSize}
        footer={{ mode: "summary" }}
        serverSide={{
          totalItems: response?.total ?? 0,
          isLoading,
          onSortingChange: setSorting,
          onPaginationChange: (idx, size) => {
            setPageIndex(idx);
            setPageSize(size);
          },
          onSearchTermChange: () => {
            // search state is already managed above via searchTerm prop;
            // this callback is useful for analytics or debouncing
          },
        }}
      />
    </div>
  );
}
```

## Sizing

The `size` prop (`"regular"` or `"small"`) affects:

- Qualifier column width (56px vs 40px)
- Actions column width (88px vs 20px)
- Footer text styles and pagination size
- All child components via `TableSizeContext`

Column widths can be responsive to size using a function:

```ts
// In types.ts, width accepts:
width: ColumnWidth | ((size: TableSize) => ColumnWidth)

// Example (this is what qualifier/actions use internally):
width: (size) => size === "small" ? { fixed: 40 } : { fixed: 56 }
```

### Width system

Data columns use **weight-based proportional distribution**. A column with `weight: 40` gets twice the space of one with `weight: 20`. When the container is narrower than the sum of `minWidth` values, columns clamp to their minimums.

Fixed columns (`{ fixed: N }`) take exactly N pixels and don't participate in proportional distribution.

Resizing uses **splitter semantics**: dragging a column border grows that column and shrinks its neighbor by the same amount, keeping total width constant.

## Advanced Examples

### Scrollable table with pinned header

```tsx
<DataTable
  data={allRows}
  columns={columns}
  height={300}
  headerBackground="var(--background-tint-00)"
/>
```

### Hidden columns on load

```tsx
<DataTable
  data={data}
  columns={columns}
  initialColumnVisibility={{ department: false, joinDate: false }}
  footer={{ mode: "selection" }}
/>
```

### Icon-based data column

```tsx
const STATUS_ICONS = {
  active: SvgCheckCircle,
  pending: SvgClock,
  inactive: SvgAlertCircle,
} as const;

tc.column("status", {
  header: "Status",
  weight: 14,
  minWidth: 80,
  cell: (value) => (
    <Content
      sizePreset="main-ui"
      variant="body"
      icon={STATUS_ICONS[value]}
      title={value.charAt(0).toUpperCase() + value.slice(1)}
    />
  ),
})
```

### Non-selectable qualifier with icons

```ts
tc.qualifier({
  content: "icon",
  getIcon: (row) => row.icon,
  selectable: false,
  header: false,
})
```

### Small variant in a bordered container

```tsx
<div className="border border-border-01 rounded-lg overflow-hidden">
  <DataTable
    data={data}
    columns={columns}
    size="small"
    pageSize={10}
    footer={{ mode: "selection" }}
  />
</div>
```

### Server-side pagination

Minimal wiring for server-side mode — manage sorting/pagination state externally and pass the current page slice as `data`.

```tsx
<DataTable
  data={currentPageRows}
  columns={columns}
  getRowId={(row) => row.id}
  searchTerm={searchTerm}
  pageSize={pageSize}
  footer={{ mode: "summary" }}
  serverSide={{
    totalItems: totalCount,
    isLoading,
    onSortingChange: setSorting,
    onPaginationChange: (idx, size) => {
      setPageIndex(idx);
      setPageSize(size);
    },
    onSearchTermChange: (term) => setSearchTerm(term),
  }}
/>
```

### Custom row click handler

```tsx
<DataTable
  data={data}
  columns={columns}
  onRowClick={(row) => router.push(`/users/${row.id}`)}
/>
```

## Source Files

| File | Purpose |
|---|---|
| `DataTable.tsx` | Main component |
| `columns.ts` | `createTableColumns` builder |
| `types.ts` | All TypeScript interfaces |
| `hooks/useDataTable.ts` | TanStack table wrapper hook |
| `hooks/useColumnWidths.ts` | Weight-based width system |
| `hooks/useDraggableRows.ts` | DnD hook (`@dnd-kit`) |
| `Footer.tsx` | Selection / Summary footer modes |
| `TableSizeContext.tsx` | Size context provider |
