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
} from "@opal/components/table/types";
import type { TableSize } from "@opal/components/table/TableSizeContext";
import type { IconFunctionComponent } from "@opal/types";
import type { SortDirection } from "@opal/components/table/TableHead";

// ---------------------------------------------------------------------------
// Qualifier column config
// ---------------------------------------------------------------------------

interface QualifierConfig<TData> {
  /** Content type for body-row `<TableQualifier>`. @default "simple" */
  content?: QualifierContentType;
  /** Return the icon component to render for a row (for "icon" content). */
  getContent?: (row: TData) => IconFunctionComponent;
  /** Return the image URL to render for a row (for "image" content). */
  getImageSrc?: (row: TData) => string;
  /** Return the image alt text for a row (for "image" content). @default "" */
  getImageAlt?: (row: TData) => string;
  /** Show a tinted background container behind the content. @default false */
  background?: boolean;
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

interface ActionsConfig<TData = any> {
  /** Show column visibility popover. @default true */
  showColumnVisibility?: boolean;
  /** Show sorting popover. @default true */
  showSorting?: boolean;
  /** Footer text for the sorting popover. */
  sortingFooterText?: string;
  /** Optional cell renderer for row-level action buttons. */
  cell?: (row: TData) => ReactNode;
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
  actions(config?: ActionsConfig<TData>): OnyxActionsColumn<TData>;
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
 *   tc.qualifier({ content: "icon", getContent: (r) => UserIcon }),
 *   tc.column("name", { header: "Name", weight: 23 }),
 *   tc.column("email", { header: "Email", weight: 28 }),
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
          size === "md" ? { fixed: 36 } : { fixed: 44 },
        content,
        getContent: config?.getContent,
        getImageSrc: config?.getImageSrc,
        getImageAlt: config?.getImageAlt,
        background: config?.background,
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
        width: { weight, minWidth: Math.max(header.length * 8 + 40, 80) },
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

    actions(config?: ActionsConfig<TData>): OnyxActionsColumn<TData> {
      const def: ColumnDef<TData, any> = {
        id: "__actions",
        enableHiding: false,
        enableSorting: false,
        enableResizing: false,
        // Header rendering is handled by DataTable based on the actions config
        header: () => null,
        cell: config?.cell
          ? (info: CellContext<TData, any>) => config.cell!(info.row.original)
          : () => null,
      };

      const showVisibility = config?.showColumnVisibility ?? true;
      const showSorting = config?.showSorting ?? true;
      const buttonCount = (showVisibility ? 1 : 0) + (showSorting ? 1 : 0);

      // Icon button sizes: "md" button = 28px, "sm" button = 24px
      // px-1 on .tbl-actions = 4px each side = 8px total
      const BUTTON_MD = 28;
      const BUTTON_SM = 24;
      const PADDING = 8;

      return {
        kind: "actions",
        id: "__actions",
        def,
        width: (size: TableSize) => ({
          fixed:
            Math.max(
              buttonCount * (size === "md" ? BUTTON_SM : BUTTON_MD),
              size === "md" ? BUTTON_SM : BUTTON_MD
            ) + PADDING,
        }),
        showColumnVisibility: showVisibility,
        showSorting: showSorting,
        sortingFooterText: config?.sortingFooterText,
      };
    },
  };
}
