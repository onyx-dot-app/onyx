# Table

Config-driven table component with sorting, pagination, column visibility,
row selection, drag-and-drop reordering, and server-side mode.

## Usage

```tsx
import { Table, createTableColumns } from "@opal/components";

interface User {
  id: string;
  email: string;
  name: string | null;
  status: "active" | "invited";
}

const tc = createTableColumns<User>();

const columns = [
  tc.qualifier({ content: "avatar-user", getInitials: (r) => r.name?.[0] ?? "?" }),
  tc.column("email", {
    header: "Name",
    weight: 22,
    minWidth: 140,
    cell: (email, row) => <span>{row.name ?? email}</span>,
  }),
  tc.column("status", {
    header: "Status",
    weight: 14,
    cell: (status) => <span>{status}</span>,
  }),
  tc.actions(),
];

function UsersTable({ users }: { users: User[] }) {
  return (
    <Table
      data={users}
      columns={columns}
      getRowId={(r) => r.id}
      pageSize={10}
      footer={{ mode: "summary" }}
    />
  );
}
```

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `data` | `TData[]` | required | Row data array |
| `columns` | `OnyxColumnDef<TData>[]` | required | Column definitions from `createTableColumns()` |
| `getRowId` | `(row: TData) => string` | required | Unique row identifier |
| `pageSize` | `number` | `10` | Rows per page (`Infinity` disables pagination) |
| `size` | `"md" \| "lg"` | `"lg"` | Density variant |
| `footer` | `DataTableFooterConfig` | — | Footer mode (`"selection"` or `"summary"`) |
| `initialSorting` | `SortingState` | — | Initial sort state |
| `initialColumnVisibility` | `VisibilityState` | — | Initial column visibility |
| `draggable` | `DataTableDraggableConfig` | — | Enable drag-and-drop reordering |
| `onSelectionChange` | `(ids: string[]) => void` | — | Selection callback |
| `onRowClick` | `(row: TData) => void` | — | Row click handler |
| `searchTerm` | `string` | — | Global text filter |
| `height` | `number \| string` | — | Max scrollable height |
| `headerBackground` | `string` | — | Sticky header background |
| `serverSide` | `ServerSideConfig` | — | Server-side pagination/sorting/filtering |
| `emptyState` | `ReactNode` | — | Empty state content |

## Column Builder

`createTableColumns<TData>()` returns a builder with:

- `tc.qualifier(opts)` — leading avatar/icon/checkbox column
- `tc.column(accessor, opts)` — data column with sorting/resizing
- `tc.display(opts)` — non-accessor custom column
- `tc.actions(opts)` — trailing actions column with visibility/sorting popovers

## Footer Modes

- **`"selection"`** — shows selection count, optional view/clear buttons, count pagination
- **`"summary"`** — shows "Showing X~Y of Z", list pagination, optional extra element
