# Table

Config-driven table component with sorting, pagination, column visibility,
row selection, drag-and-drop reordering, and server-side mode.

## Usage

Columns are plain literals told apart by `kind`, the same shape as Dropdown
items. Annotate the array as `TableColumn<TData>[]` so each `cell` gets its
field's type.

```tsx
import { Table, type TableColumn } from "@opal/components";
import { SvgUser } from "@opal/icons";

interface User {
  id: string;
  email: string;
  name: string | null;
  status: "active" | "invited";
}

const columns: TableColumn<User>[] = [
  { kind: "qualifier", content: "icon", icon: () => SvgUser },
  {
    kind: "data",
    field: "email",
    title: "Name",
    weight: 22,
    cell: (email, row) => <span>{row.name ?? email}</span>,
  },
  {
    kind: "data",
    field: "status",
    title: "Status",
    weight: 14,
    cell: (status) => <span>{status}</span>,
  },
  { kind: "actions" },
];

function UsersTable({ users }: { users: User[] }) {
  return (
    <Table
      label="Users"
      items={users}
      columns={columns}
      getRowId={(r) => r.id}
      pageSize={10}
      footer={{}}
    />
  );
}
```

## Props

| Prop                      | Type                                  | Default       | Description                                                     |
| ------------------------- | ------------------------------------- | ------------- | --------------------------------------------------------------- |
| `items`                   | `TData[]`                             | required      | The rows                                                        |
| `columns`                 | `TableColumn<TData>[]`                | required      | The columns, in order (see [Columns](#columns))                 |
| `getRowId`                | `(row: TData) => string`              | required      | Unique row identifier                                           |
| `label`                   | `string`                              | —             | The table's accessible name                                     |
| `pageSize`                | `number`                              | `10`          | Rows per page (`Infinity` disables pagination)                  |
| `size`                    | `2.25 \| 2.75`                       | `2.75`        | Each body row's height in rem: 36px or 44px                     |
| `footer`                  | `DataTableFooterConfig`               | —             | Footer configuration (mode is derived from `selectionBehavior`) |
| `selectionBehavior`       | `"no-select" \| "single-select" \| "multi-select"` | `"no-select"` | Row selection behavior                       |
| `values`                  | `ReadonlySet<string>`                 | —             | The selected row IDs. Given, the selection is controlled        |
| `onSelectionChange`       | `(values: ReadonlySet<string>) => void` | —           | Called with the next selection                                  |
| `initialViewSelected`     | `boolean`                             | `false`       | Start filtered to `values`, when it is non-empty at mount       |
| `initialSorting`          | `SortingState`                        | —             | Initial sort state                                              |
| `initialColumnVisibility` | `VisibilityState`                     | —             | Initial column visibility                                       |
| `draggable`               | `DataTableDraggableConfig`            | —             | Enable drag-and-drop reordering                                 |
| `onRowClick`              | `(row: TData) => void`                | —             | Row click handler                                               |
| `getRowLabel`             | `(row: TData) => string`              | —             | Accessible action label for clickable rows                      |
| `query`                   | `string`                              | —             | Filters rows to data-column values that contain it              |
| `height`                  | `number \| string`                    | —             | Max scrollable height                                           |
| `serverSide`              | `ServerSideConfig`                    | —             | Server-side pagination/sorting/filtering (`onQueryChange` for `query`) |
| `emptyState`              | `ReactNode`                           | —             | Empty state content                                             |
| `showHeader`              | `boolean`                             | `true`        | Render the header row. Hiding it also hides header sorting, resizing, select-all and the actions popovers |

## Columns

| `kind`        | Fields                                                                                                   |
| ------------- | -------------------------------------------------------------------------------------------------------- |
| `"qualifier"` | `content?` (`"simple" \| "icon" \| "image"`), `icon?(row)`, `imageSrc?(row)`, `imageAlt?(row)`, `background?`, `iconSize?` |
| `"data"`      | `field` (a key of the row) or `id` + `value(row)`; `title`, `cell?(value, row)`, `sortable?`, `resizable?`, `hideable?`, `sortIcon?`, `weight?`, `alignment?` |
| `"display"`   | `id`, `title?`, `cell(row)`, `width` (`{ weight, minWidth? }` or `{ fixed }`), `hideable?`, `alignment?` |
| `"actions"`   | `cell?(row)`, `showColumnVisibility?`, `showSorting?`, `sortingFooterText?`                              |

A `field` column's value is that field; a `value` column's is whatever `value`
returns (a string, number, boolean, null or undefined). Either way the value
drives sorting and `query`.

## Footer

The footer mode is derived automatically from `selectionBehavior`:

- **Selection footer** (when `selectionBehavior` is `"single-select"` or `"multi-select"`) — shows selection count, optional view/clear buttons, count pagination
- **Summary footer** (when `selectionBehavior` is `"no-select"` or omitted) — shows "Showing X\~Y of Z", list pagination, optional extra element
