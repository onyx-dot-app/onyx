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

| Prop                      | Type                                               | Default                            | Description                                                                                             |
| ------------------------- | -------------------------------------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `items`                   | `TData[]`                                          | required                           | The rows                                                                                                |
| `columns`                 | `TableColumn<TData>[]`                             | required                           | The columns, in order (see [Columns](#columns))                                                         |
| `getRowId`                | `(row: TData) => string`                           | required                           | Unique row identifier                                                                                   |
| `label`                   | `string`                                           | —                                  | The table's accessible name                                                                             |
| `pageSize`                | `number \| false`                                  | `10` with a footer, else every row | Rows per page; `false` shows every row. Paging always brings the footer                                 |
| `size`                    | `2.25 \| 2.75`                                     | `2.75`                             | Each body row's height in rem: 36px or 44px                                                             |
| `footer`                  | `boolean \| DataTableFooterConfig`                 | —                                  | `true` for the default footer, or its configuration (mode is derived from `selectionBehavior`)          |
| `selectionBehavior`       | `"no-select" \| "single-select" \| "multi-select"` | `"no-select"`                      | Row selection behavior                                                                                  |
| `values`                  | `ReadonlySet<string>`                              | —                                  | The selected row IDs. Given, the selection is controlled                                                |
| `onSelectionChange`       | `(values: ReadonlySet<string>) => void`            | —                                  | Called with the next selection                                                                          |
| `selectionDisabled` | `boolean` | `false` | Locks checkboxes, row selection and footer clearing; row actions and pagination stay available |
| `selectAllLabel` | `string` | localized | Accessible label for the header checkbox |
| `getRowSelectionLabel` | `(row: TData) => string` | localized | Accessible label for each row checkbox |
| `initialViewSelected`     | `boolean`                                          | `false`                            | Start filtered to `values`, when it is non-empty at mount                                               |
| `initialSorting`          | `SortingState`                                     | —                                  | Initial sort state                                                                                      |
| `initialColumnVisibility` | `VisibilityState`                                  | —                                  | Initial column visibility                                                                               |
| `draggable`               | `DataTableDraggableConfig`                         | —                                  | Enable drag-and-drop reordering                                                                         |
| `onRowClick`              | `(row: TData) => void`                             | —                                  | Row click handler                                                                                       |
| `getRowLabel`             | `(row: TData) => string`                           | —                                  | Accessible action label for clickable rows                                                              |
| `query`                   | `string`                                           | —                                  | Filters rows to data-column values that contain it                                                      |
| `height`                  | `number \| string`                                 | —                                  | Max scrollable height                                                                                   |
| `serverSide`              | `ServerSideConfig`                                 | —                                  | Server-side pagination/sorting/filtering (`onQueryChange` for `query`)                                  |
| `emptyState`              | `ReactNode`                                        | —                                  | Empty state content                                                                                     |
| `header`                  | `boolean`                                          | `true`                             | Show the header row. Hiding it also hides header sorting, resizing, select-all and the actions popovers |

Set `rowHeight="content"` for multiline cells. Rows grow to fit their content,
with `size` as the minimum height. Headers wrap within their columns in this mode.
The default, `"fixed"`, keeps the selected size.

## Columns

| `kind`        | Fields                                                                                                                                                                     |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `"qualifier"` | `content?` (`"checkbox" \| "icon" \| "image"`), `icon?(row)`, `imageSrc?(row)`, `imageAlt?(row)`, `background?`, `avatar?`                                                 |
| `"data"`      | `field` (a key of the row) or `id` + `value(row)`; `title`, `cell?(value, row)`, `sortable?`, `resizable?`, `hideable?`, `sortIcon?`, `weight?`, `alignment?`, `truncate?` |
| `"display"`   | `id`, `title?`, `cell(row)`, `width` (`{ weight, minWidth? }` or `{ fixed }`), `hideable?`, `alignment?`                                                                   |
| `"actions"`   | `cell?(row)`, `showColumnVisibility?`, `showSorting?`, `sortingFooterText?`                                                                                                |

A `field` column's value is that field; a `value` column's is whatever `value`
returns (a string, number, boolean, null or undefined). Either way the value
drives sorting and `query`.

## Footer

The footer mode is derived automatically from `selectionBehavior`:

- **Selection footer** (when `selectionBehavior` is `"single-select"` or `"multi-select"`) — shows selection count, optional view/clear buttons, count pagination
- **Summary footer** (when `selectionBehavior` is `"no-select"` or omitted) — shows "Showing X\~Y of Z", list pagination, optional extra element


## Selection and focus

Use a `qualifier` column with `selectionBehavior="multi-select"` for header and row checkboxes.
The header selects all filtered rows, across pages. Its default label is "Select all rows".
A partial selection becomes a full selection when checked.
Caller labels override the localized OpalStrings defaults. Default row labels use `getRowLabel`, or the row ID.

Checkbox labels provide 36px targets at the default row size, and 28px targets for compact rows.
Checkbox clicks and keyboard presses change selection without calling `onRowClick`.
Enter or Space on a focused clickable row calls `onRowClick`.
Rows use the shared neutral keyboard focus state and an inset neutral outline.
The outline keeps keyboard focus visible on selected rows. Checked boxes identify selection.
