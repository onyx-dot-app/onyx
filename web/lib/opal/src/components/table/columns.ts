import type { ReactNode } from "react";
import {
  createColumnHelper,
  type ColumnDef,
  type CellContext,
} from "@tanstack/react-table";
import type {
  TableColumn,
  OnyxColumnDef,
  OnyxQualifierColumn,
  OnyxDataColumn,
  OnyxDisplayColumn,
  OnyxActionsColumn,
  TableQualifierColumn,
  TableFieldColumn,
  TableValueColumn,
  TableDisplayColumn,
  TableActionsColumn,
  TableCellValue,
} from "@opal/components/table/types";
import type { TableSize } from "@opal/components/table/TableSizeContext";

// ---------------------------------------------------------------------------
// Resolve a `TableColumn` literal into the TanStack-backed internal column
// ---------------------------------------------------------------------------

function resolveQualifier<TData>(
  col: TableQualifierColumn<TData>
): OnyxQualifierColumn<TData> {
  const def: ColumnDef<TData, any> = createColumnHelper<TData>().display({
    id: "qualifier",
    enableResizing: false,
    enableSorting: false,
    enableHiding: false,
    // Table renders the qualifier cell from this column's config.
    cell: () => null,
  });

  return {
    kind: "qualifier",
    id: "qualifier",
    def,
    width: (size: TableSize) => (size === 2.25 ? { fixed: 36 } : { fixed: 44 }),
    content: col.content ?? "checkbox",
    getContent: col.icon,
    getImageSrc: col.imageSrc,
    getImageAlt: col.imageAlt,
    background: col.background,
    avatar: col.avatar,
  };
}

function resolveData<TData>(
  col: TableFieldColumn<TData> | TableValueColumn<TData>
): OnyxDataColumn<TData> {
  const {
    title,
    sortable = true,
    resizable = true,
    hideable = true,
    sortIcon,
    weight = 20,
    alignment,
  } = col;
  const helper = createColumnHelper<TData>();
  const options = {
    header: title,
    enableSorting: sortable,
    enableResizing: resizable,
    enableHiding: hideable,
  };

  // The two arms differ only in where the value comes from; the cell
  // renderer is handed whatever the accessor produced: a field's value or
  // a `value` column's result.
  type CellValue = TData[keyof TData] | TableCellValue;
  const cell = col.cell as
    | ((value: CellValue, row: TData) => ReactNode)
    | undefined;
  const renderCell = cell
    ? (info: CellContext<TData, CellValue>) =>
        cell(info.getValue(), info.row.original)
    : undefined;

  let id: string;
  let def: ColumnDef<TData, any>;
  if (col.value !== undefined) {
    id = col.id;
    def = helper.accessor(col.value, { ...options, id, cell: renderCell });
  } else {
    id = col.id ?? col.field;
    def = helper.accessor((row: TData) => row[col.field], {
      ...options,
      id,
      cell: renderCell,
    }) as ColumnDef<TData, any>;
  }

  return {
    kind: "data",
    id,
    def,
    width: { weight, minWidth: Math.max(title.length * 8 + 40, 80) },
    icon: sortIcon,
    alignment,
  };
}

function resolveDisplay<TData>(
  col: TableDisplayColumn<TData>
): OnyxDisplayColumn<TData> {
  const def: ColumnDef<TData, any> = createColumnHelper<TData>().display({
    id: col.id,
    header: col.title,
    enableHiding: col.hideable ?? true,
    enableSorting: false,
    enableResizing: false,
    cell: (info) => col.cell(info.row.original),
  });

  return {
    kind: "display",
    id: col.id,
    def,
    width: col.width,
    alignment: col.alignment,
  };
}

// Icon button sizes: "md" button = 28px, "sm" button = 24px.
// px-1 on .tbl-actions = 4px each side = 8px total.
const ACTION_BUTTON_MD = 28;
const ACTION_BUTTON_SM = 24;
const ACTIONS_PADDING = 8;

function resolveActions<TData>(
  col: TableActionsColumn<TData>
): OnyxActionsColumn<TData> {
  const { cell } = col;
  const def: ColumnDef<TData, any> = {
    id: "__actions",
    enableHiding: false,
    enableSorting: false,
    enableResizing: false,
    // Table renders the header's popovers from this column's config.
    header: () => null,
    cell: cell
      ? (info: CellContext<TData, unknown>) => cell(info.row.original)
      : () => null,
  };

  const showColumnVisibility = col.showColumnVisibility ?? true;
  const showSorting = col.showSorting ?? true;
  const buttonCount = (showColumnVisibility ? 1 : 0) + (showSorting ? 1 : 0);

  return {
    kind: "actions",
    id: "__actions",
    def,
    width: (size: TableSize) => {
      const button = size === 2.25 ? ACTION_BUTTON_SM : ACTION_BUTTON_MD;
      return {
        fixed: Math.max(buttonCount * button, button) + ACTIONS_PADDING,
      };
    },
    showColumnVisibility,
    showSorting,
    sortingFooterText: col.sortingFooterText,
  };
}

/** Turn a `TableColumn` literal into the internal, TanStack-backed column. */
export function resolveColumn<TData>(
  col: TableColumn<TData>
): OnyxColumnDef<TData> {
  switch (col.kind) {
    case "qualifier":
      return resolveQualifier(col);
    case "data":
      return resolveData(col);
    case "display":
      return resolveDisplay(col);
    case "actions":
      return resolveActions(col);
  }
}
