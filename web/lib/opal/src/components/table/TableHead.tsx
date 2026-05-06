import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import { useTableSize } from "@opal/components/table/TableSizeContext";
import type { WithoutStyles } from "@opal/types";
import { Button } from "@opal/components";
import { SvgChevronDown, SvgChevronUp, SvgHandle, SvgSort } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";

export type SortDirection = "none" | "ascending" | "descending";

/**
 * A table header cell with optional sort controls and a resize handle indicator.
 * Renders as a `<th>` element with Figma-matched typography and spacing.
 */
interface TableHeadCustomProps {
  /** Header label content. */
  children: React.ReactNode;
  /** Current sort state. When omitted, no sort button is shown. */
  sorted?: SortDirection;
  /** Called when the sort button is clicked. Required to show the sort button. */
  onSort?: () => void;
  /** When `true`, renders a thin resize handle on the right edge. */
  resizable?: boolean;
  /** Called when a resize drag begins on the handle. Attach TanStack's
   *  `header.getResizeHandler()` here to enable column resizing. */
  onResizeStart?: (event: React.MouseEvent | React.TouchEvent) => void;
  /** Override the sort icon for this column. Receives the current sort state and
   *  returns the icon component to render. Falls back to the built-in icons. */
  icon?: (sorted: SortDirection) => IconFunctionComponent;
  /** Text alignment for the column. Defaults to `"left"`. */
  alignment?: "left" | "center" | "right";
  /** Column width in pixels. Applied as an inline style on the `<th>`. */
  width?: number;
  /** When `true`, shows a bottom border on hover. Defaults to `true`. */
  bottomBorder?: boolean;
}

type TableHeadProps = WithoutStyles<
  TableHeadCustomProps &
    Omit<
      React.ThHTMLAttributes<HTMLTableCellElement>,
      keyof TableHeadCustomProps
    >
>;

/**
 * Table header cell primitive. Displays a column label with optional sort
 * functionality and a resize handle indicator.
 */
function defaultSortIcon(sorted: SortDirection): IconFunctionComponent {
  switch (sorted) {
    case "ascending":
      return SvgChevronUp;
    case "descending":
      return SvgChevronDown;
    default:
      return SvgSort;
  }
}

const alignmentThClass = {
  left: "text-left",
  center: "text-center",
  right: "text-right",
} as const;

export default function TableHead({
  children,
  sorted,
  onSort,
  icon: iconFn = defaultSortIcon,
  resizable,
  onResizeStart,
  alignment = "left",
  width,
  bottomBorder = true,
  ...thProps
}: TableHeadProps) {
  const resolvedSize = useTableSize();
  const isSmall = resolvedSize === "md";
  return (
    <th
      {...thProps}
      scope="col"
      style={width != null ? { width } : undefined}
      className={cn("table-head group", alignmentThClass[alignment])}
      data-size={resolvedSize}
      data-bottom-border={bottomBorder || undefined}
    >
      <div className="flex items-center gap-1">
        <div className="table-head-label">
          <Text
            font={isSmall ? "secondary-action" : "main-ui-action"}
            color="text-04"
            maxLines={1}
          >
            {children ? String(children) : undefined}
          </Text>
        </div>
        <div
          className={cn(
            "table-head-sort",
            "opacity-0 group-hover:opacity-100 transition-opacity"
          )}
        >
          {onSort && (
            <Button
              icon={iconFn(sorted ?? "none")}
              onClick={onSort}
              tooltip="Sort"
              tooltipSide="top"
              prominence="internal"
              size="sm"
            />
          )}
        </div>
      </div>
      {resizable && (
        <div
          onMouseDown={onResizeStart}
          onTouchStart={onResizeStart}
          className={cn(
            "absolute right-0 top-0 flex h-full items-center",
            "text-border-02",
            "opacity-0 group-hover:opacity-100",
            "cursor-col-resize",
            "select-none touch-none"
          )}
        >
          <SvgHandle size={22} className="stroke-border-02" />
        </div>
      )}
    </th>
  );
}
