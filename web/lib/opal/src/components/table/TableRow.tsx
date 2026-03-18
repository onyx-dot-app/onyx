"use client";

import { cn } from "@opal/utils";
import { useTableSize } from "./TableSizeContext";
import type { TableSize } from "./TableSizeContext";
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
  /** Disables interaction and applies disabled styling */
  disabled?: boolean;
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
  selected,
  disabled,
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
      data-drag-handle={showDragHandle || undefined}
      data-selected={selected || undefined}
      data-disabled={disabled || undefined}
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
            onMouseDown={(e) => e.preventDefault()}
            {...listeners}
          >
            <SvgHandle
              size={resolvedSize === "md" ? 12 : 16}
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
  selected,
  disabled,
  ref,
  ...props
}: TableRowProps) {
  if (sortableId) {
    return (
      <SortableTableRow
        sortableId={sortableId}
        showDragHandle={showDragHandle}
        size={size}
        selected={selected}
        disabled={disabled}
        ref={ref}
        {...props}
      />
    );
  }

  return (
    <tr
      ref={ref}
      className="tbl-row group/row"
      data-selected={selected || undefined}
      data-disabled={disabled || undefined}
      {...props}
    />
  );
}

export default TableRow;
export type { TableRowProps };
