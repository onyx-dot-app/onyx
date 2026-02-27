import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { Button } from "@opal/components";
import { SvgHandle } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";

type SortDirection = "none" | "ascending" | "descending";

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
  /** Override the sort icon for this column. Receives the current sort state and
   *  returns the icon component to render. Falls back to the built-in icons. */
  icon?: (sorted: SortDirection) => IconFunctionComponent;
  /** Text alignment for the column. Defaults to `"left"`. */
  alignment?: "left" | "center" | "right";
  /** Cell density. `"small"` uses tighter padding for denser layouts. */
  size?: "regular" | "small";
}

type TableHeadProps = TableHeadCustomProps &
  Omit<
    React.ThHTMLAttributes<HTMLTableCellElement>,
    keyof TableHeadCustomProps
  >;

/**
 * Table header cell primitive. Displays a column label with optional sort
 * functionality and a resize handle indicator.
 */
const alignmentThClass = {
  left: "text-left",
  center: "text-center",
  right: "text-right",
} as const;

const alignmentFlexClass = {
  left: "justify-start",
  center: "justify-center",
  right: "justify-end",
} as const;

export default function TableHead({
  children,
  sorted,
  onSort,
  icon: iconFn,
  resizable,
  alignment = "left",
  size = "regular",
  className,
  ...thProps
}: TableHeadProps) {
  const isSmall = size === "small";
  const resolvedIcon = iconFn;
  return (
    <th
      {...thProps}
      className={cn(
        "group relative",
        alignmentThClass[alignment],
        isSmall ? "p-1.5" : "px-2 py-1",
        "border-b border-transparent group-hover:border-border-03",
        className
      )}
    >
      <div
        className={cn("flex items-center gap-1", alignmentFlexClass[alignment])}
      >
        <div className={isSmall ? "py-1" : "py-2"}>
          <Text
            mainUiAction={!isSmall}
            secondaryAction={isSmall}
            text04
            className="truncate"
          >
            {children}
          </Text>
        </div>
        <div
          className={cn(
            !isSmall && "py-1.5",
            "opacity-0 group-hover:opacity-100 transition-opacity"
          )}
        >
          {onSort && resolvedIcon && (
            <Button
              icon={resolvedIcon(sorted ?? "none")}
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
          className={cn(
            "absolute right-0 top-0 flex h-full items-center",
            "text-border-02",
            "opacity-0 group-hover:opacity-100",
            "cursor-col-resize"
          )}
        >
          <SvgHandle size={22} className="stroke-border-02" />
        </div>
      )}
    </th>
  );
}
