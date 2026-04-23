"use client";

import type { WithoutStyles } from "@/types";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TableRowProps
  extends WithoutStyles<React.HTMLAttributes<HTMLTableRowElement>> {
  ref?: React.Ref<HTMLTableRowElement>;
  selected?: boolean;
  /** Disables interaction and applies disabled styling */
  disabled?: boolean;
  /** When provided, makes this row sortable via @dnd-kit */
  sortableId?: string;
}

// ---------------------------------------------------------------------------
// Internal: sortable row
// ---------------------------------------------------------------------------

function SortableTableRow({
  sortableId,
  selected,
  disabled,
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
      className="tbl-row group/row"
      data-selected={selected || undefined}
      data-disabled={disabled || undefined}
      {...listeners}
      {...props}
    >
      {children}
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function TableRow({
  sortableId,
  selected,
  disabled,
  ref,
  ...props
}: TableRowProps) {
  if (sortableId) {
    return (
      <SortableTableRow
        sortableId={sortableId}
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
