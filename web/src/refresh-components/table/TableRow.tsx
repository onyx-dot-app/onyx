"use client";

import { cn } from "@/lib/utils";
import { useTableSize } from "@/refresh-components/table/TableSizeContext";
import type { TableSize } from "@/refresh-components/table/TableSizeContext";
import type { WithoutStyles } from "@/types";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { SvgHandle } from "@opal/icons";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TableRowProps
  extends WithoutStyles<React.HTMLAttributes<HTMLTableRowElement>> {
  ref?: React.Ref<HTMLTableRowElement>;
  selected?: boolean;
  /** Visual variant: "table" adds a bottom border, "list" adds rounded corners. Defaults to "list". */
  variant?: "table" | "list";
  /** When provided, makes this row sortable via @dnd-kit */
  sortableId?: string;
  /** Show drag handle overlay. Defaults to true when sortableId is set. */
  showDragHandle?: boolean;
  /** Size variant for the drag handle */
  size?: TableSize;
}

// ---------------------------------------------------------------------------
// Internal: sortable row
// ---------------------------------------------------------------------------

function SortableTableRow({
  sortableId,
  showDragHandle = true,
  size,
  variant = "list",
  selected,
  ref: _externalRef,
  children,
  ...props
}: TableRowProps) {
  const contextSize = useTableSize();
  const resolvedSize = size ?? contextSize;

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: sortableId! });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0 : undefined,
  };

  return (
    <tr
      ref={setNodeRef}
      style={style}
      className="tbl-row group/row"
      data-variant={variant}
      data-drag-handle={showDragHandle || undefined}
      {...attributes}
      {...props}
    >
      {children}
      {showDragHandle && (
        <td
          style={{
            width: 0,
            padding: 0,
            position: "relative",
            zIndex: 20,
          }}
        >
          <button
            type="button"
            className={cn(
              "absolute right-0 top-1/2 -translate-y-1/2 cursor-grab",
              "opacity-0 group-hover/row:opacity-100 transition-opacity",
              "flex items-center justify-center rounded"
            )}
            aria-label="Drag to reorder"
            {...listeners}
          >
            <SvgHandle
              size={resolvedSize === "small" ? 12 : 16}
              className="text-border-02"
            />
          </button>
        </td>
      )}
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

function TableRow({
  sortableId,
  showDragHandle,
  size,
  variant = "list",
  selected,
  ref,
  ...props
}: TableRowProps) {
  if (sortableId) {
    return (
      <SortableTableRow
        sortableId={sortableId}
        showDragHandle={showDragHandle}
        size={size}
        variant={variant}
        selected={selected}
        ref={ref}
        {...props}
      />
    );
  }

  return (
    <tr
      ref={ref}
      className="tbl-row group/row"
      data-variant={variant}
      {...props}
    />
  );
}

export default TableRow;
export type { TableRowProps };
