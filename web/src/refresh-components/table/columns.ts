import type { ReactNode } from "react";
import {
  createColumnHelper,
  type ColumnDef,
  type DeepKeys,
  type DeepValue,
  type CellContext,
} from "@tanstack/react-table";
import type {
  ColumnWidth,
  QualifierContentType,
  OnyxQualifierColumn,
  OnyxDataColumn,
  OnyxDisplayColumn,
  OnyxActionsColumn,
  OnyxColumnDef,
} from "@/refresh-components/table/types";
import type { TableSize } from "@/refresh-components/table/TableSizeContext";
import type { IconFunctionComponent } from "@opal/types";
import type { SortDirection } from "@/refresh-components/table/TableHead";

// ---------------------------------------------------------------------------
// Qualifier column config
// ---------------------------------------------------------------------------

interface QualifierConfig<TData> {
  /** Content type for body-row `<TableQualifier>`. @default "simple" */
  content?: QualifierContentType;
  /** Content type for the header `<TableQualifier>`. @default "simple" */
  headerContentType?: QualifierContentType;
  /** Extract initials from a row (for "avatar-user" content). */
  getInitials?: (row: TData) => string;
  /** Extract icon from a row (for "icon" / "avatar-icon" content). */
  getIcon?: (row: TData) => IconFunctionComponent;
  /** Extract image src from a row (for "image" content). */
  getImageSrc?: (row: TData) => string;
  /** Whether to show selection checkboxes on the qualifier. @default true */
  selectable?: boolean;
  /** Whether to render qualifier content in the header. @default true */
  header?: boolean;
}

// ---------------------------------------------------------------------------
// Data column config
// ---------------------------------------------------------------------------

interface DataColumnConfig<TData, TValue> {
  /** Column header label. */
  header: string;
  /** Custom cell renderer. If omitted, the value is rendered as a string. */
  cell?: (value: TValue, row: TData) => ReactNode;
  /** Enable sorting for this column. @default true */
  enableSorting?: boolean;
  /** Enable resizing for this column. @default true */
  enableResizing?: boolean;
  /** Enable hiding for this column. @default true */
  enableHiding?: boolean;
  /** Override the sort icon for this column. */
  icon?: (sorted: SortDirection) => IconFunctionComponent;
  /** Column weight for proportional distribution. @default 20 */
  weight?: number;
  /** Minimum column width in pixels. @default 50 */
  minWidth?: number;
}

// ---------------------------------------------------------------------------
// Display column config
// ---------------------------------------------------------------------------

interface DisplayColumnConfig<TData> {
  /** Unique column ID. */
  id: string;
  /** Column header label. */
  header?: string;
  /** Cell renderer. */
  cell: (row: TData) => ReactNode;
  /** Column width config. */
  width: ColumnWidth;
  /** Enable hiding. @default true */
  enableHiding?: boolean;
}

// ---------------------------------------------------------------------------
// Actions column config
// ---------------------------------------------------------------------------

interface ActionsConfig {
  /** Show column visibility popover. @default true */
  showColumnVisibility?: boolean;
  /** Show sorting popover. @default true */
  showSorting?: boolean;
  /** Footer text for the sorting popover. */
  sortingFooterText?: string;
}

// ---------------------------------------------------------------------------
// Builder return type
// ---------------------------------------------------------------------------

interface TableColumnsBuilder<TData> {
  /** Create a qualifier (leading avatar/checkbox) column. */
  qualifier(config?: QualifierConfig<TData>): OnyxQualifierColumn<TData>;

  /** Create a data (accessor) column. */
  column<TKey extends DeepKeys<TData>>(
    accessor: TKey,
    config: DataColumnConfig<TData, DeepValue<TData, TKey>>
  ): OnyxDataColumn<TData>;

  /** Create a display (non-accessor) column. */
  displayColumn(config: DisplayColumnConfig<TData>): OnyxDisplayColumn<TData>;

  /** Create an actions column (visibility/sorting popovers). */
  actions(config?: ActionsConfig): OnyxActionsColumn<TData>;
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/**
 * Creates a typed column builder for a given row type.
 *
 * Internally uses TanStack's `createColumnHelper<TData>()` to get free
 * `DeepKeys`/`DeepValue` inference for accessor columns.
 *
 * **Important**: Define columns at module scope or wrap in `useMemo` to avoid
 * creating new array references per render.
 *
 * @example
 * ```ts
 * const tc = createTableColumns<TeamMember>();
 * const columns = [
 *   tc.qualifier({ content: "avatar-user", getInitials: (r) => r.initials }),
 *   tc.column("name", { header: "Name", weight: 23, minWidth: 120 }),
 *   tc.column("email", { header: "Email", weight: 28, minWidth: 150 }),
 *   tc.actions(),
 * ];
 * ```
 */
export function createTableColumns<TData>(): TableColumnsBuilder<TData> {
  const helper = createColumnHelper<TData>();

  return {
    qualifier(config?: QualifierConfig<TData>): OnyxQualifierColumn<TData> {
      const content = config?.content ?? "simple";

      const def: ColumnDef<TData, any> = helper.display({
        id: "qualifier",
        enableResizing: false,
        enableSorting: false,
        enableHiding: false,
        // Cell rendering is handled by DataTable based on the qualifier config
        cell: () => null,
      });

      return {
        kind: "qualifier",
        id: "qualifier",
        def,
        width: (size: TableSize) =>
          size === "small" ? { fixed: 40 } : { fixed: 56 },
        content,
        headerContentType: config?.headerContentType,
        getInitials: config?.getInitials,
        getIcon: config?.getIcon,
        getImageSrc: config?.getImageSrc,
        selectable: config?.selectable,
        header: config?.header,
      };
    },

    column<TKey extends DeepKeys<TData>>(
      accessor: TKey,
      config: DataColumnConfig<TData, DeepValue<TData, TKey>>
    ): OnyxDataColumn<TData> {
      const {
        header,
        cell,
        enableSorting = true,
        enableResizing = true,
        enableHiding = true,
        icon,
        weight = 20,
        minWidth = 50,
      } = config;

      const def = helper.accessor(accessor as any, {
        header,
        enableSorting,
        enableResizing,
        enableHiding,
        cell: cell
          ? (info: CellContext<TData, any>) =>
              cell(info.getValue(), info.row.original)
          : undefined,
      }) as ColumnDef<TData, any>;

      return {
        kind: "data",
        id: accessor as string,
        def,
        width: { weight, minWidth },
        icon,
      };
    },

    displayColumn(
      config: DisplayColumnConfig<TData>
    ): OnyxDisplayColumn<TData> {
      const { id, header, cell, width, enableHiding = true } = config;

      const def: ColumnDef<TData, any> = helper.display({
        id,
        header: header ?? undefined,
        enableHiding,
        enableSorting: false,
        enableResizing: false,
        cell: (info) => cell(info.row.original),
      });

      return {
        kind: "display",
        id,
        def,
        width,
      };
    },

    actions(config?: ActionsConfig): OnyxActionsColumn<TData> {
      const def: ColumnDef<TData, any> = {
        id: "__actions",
        enableHiding: false,
        enableSorting: false,
        enableResizing: false,
        // Header rendering is handled by DataTable based on the actions config
        header: () => null,
        cell: () => null,
      };

      return {
        kind: "actions",
        id: "__actions",
        def,
        width: (size: TableSize) =>
          size === "small" ? { fixed: 20 } : { fixed: 88 },
        showColumnVisibility: config?.showColumnVisibility ?? true,
        showSorting: config?.showSorting ?? true,
        sortingFooterText: config?.sortingFooterText,
      };
    },
  };
}
