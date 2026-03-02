"use client";

import { cn } from "@/lib/utils";
import type { WithoutStyles } from "@/types";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { SvgGripVertical } from "@opal/icons";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TableRowProps
  extends WithoutStyles<React.HTMLAttributes<HTMLTableRowElement>> {
  ref?: React.Ref<HTMLTableRowElement>;
  selected?: boolean;
  /** When provided, makes this row sortable via @dnd-kit */
  sortableId?: string;
  /** Show drag handle overlay. Defaults to true when sortableId is set. */
  showDragHandle?: boolean;
  /** Size variant for the drag handle */
  size?: "regular" | "small";
}

// ---------------------------------------------------------------------------
// Internal: sortable row
// ---------------------------------------------------------------------------

function SortableTableRow({
  sortableId,
  showDragHandle = true,
  size = "regular",
  selected,
  ref: _externalRef,
  children,
  ...props
}: TableRowProps) {
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
      className="group"
      {...attributes}
      {...props}
    >
      {children}
      {showDragHandle && (
        <td
          style={{
            width: 0,
            padding: 0,
            border: "none",
            position: "relative",
          }}
        >
          <button
            type="button"
            className={cn(
              "absolute top-1/2 -translate-y-1/2 cursor-grab",
              "opacity-0 group-hover:opacity-100 transition-opacity",
              "flex items-center justify-center rounded",
              "text-text-03 hover:text-text-01",
              size === "small" ? "right-1 p-0.5" : "right-2 p-1"
            )}
            aria-label="Drag to reorder"
            {...listeners}
          >
            <SvgGripVertical size={size === "small" ? 12 : 16} />
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
        ref={ref}
        {...props}
      />
    );
  }

  return <tr ref={ref} {...props} />;
}

export default TableRow;
export type { TableRowProps };
