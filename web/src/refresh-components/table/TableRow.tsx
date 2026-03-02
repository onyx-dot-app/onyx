"use client";

import { cn } from "@/lib/utils";
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
  size?: "regular" | "small";
}

// ---------------------------------------------------------------------------
// Internal: sortable row
// ---------------------------------------------------------------------------

function SortableTableRow({
  sortableId,
  showDragHandle = true,
  size = "regular",
  variant = "list",
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
      className={cn(
        "group",
        "[&>td]:bg-background-tint-00",
        variant === "table" && "[&>td]:border-b [&>td]:border-border-01",
        variant === "list" && [
          "[&>td]:bg-clip-padding",
          "[&>td]:border-y-[4px]",
          "[&>td]:border-x-0",
          "[&>td]:border-transparent",
          "[&>td:first-child]:rounded-l-12",
          showDragHandle
            ? "[&>td:nth-last-child(2)]:rounded-r-12"
            : "[&>td:last-child]:rounded-r-12",
        ]
      )}
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
          }}
        >
          <button
            type="button"
            className={cn(
              "absolute top-1/2 -translate-y-1/2 cursor-grab",
              "opacity-0 group-hover:opacity-100 transition-opacity",
              "flex items-center justify-center rounded"
            )}
            aria-label="Drag to reorder"
            {...listeners}
          >
            <SvgHandle
              size={size === "small" ? 12 : 16}
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
      className={cn(
        "[&>td]:bg-background-tint-00",
        variant === "table" && "[&>td]:border-b [&>td]:border-border-01",
        variant === "list" && [
          "[&>td]:bg-clip-padding",
          "[&>td]:border-y-[4px]",
          "[&>td]:border-x-0",
          "[&>td]:border-transparent",
          "[&>td:first-child]:rounded-l-12",
          "[&>td:last-child]:rounded-r-12",
        ]
      )}
      {...props}
    />
  );
}

export default TableRow;
export type { TableRowProps };
