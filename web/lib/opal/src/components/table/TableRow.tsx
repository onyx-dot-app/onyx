"use client";

import { cn } from "@opal/utils";
import { useTableSize } from "@opal/components/table/TableSizeContext";
import type { WithoutStyles } from "@opal/types";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { SvgHandle } from "@opal/icons";
import { useOpalStrings } from "@opal/strings";
import { Interactive } from "@opal/core";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** A body row's surface: `"primary"` on `tint-00`, `"secondary"` on `tint-01`. */
export type TableProminence = "primary" | "secondary";

export interface TableRowProps extends WithoutStyles<
  React.HTMLAttributes<HTMLTableRowElement>
> {
  ref?: React.Ref<HTMLTableRowElement>;
  /**
   * A body row's surface. Given, the row is an `Interactive.Stateful`
   * surface (like `AttachmentItemButton`) with hover, selected and disabled
   * states. Left out (the header row), it is a plain row.
   */
  prominence?: TableProminence;
  selected?: boolean;
  /** Disables interaction and applies disabled styling */
  disabled?: boolean;
  /** When provided, makes this row sortable via @dnd-kit */
  sortableId?: string;
  /** Show drag handle overlay. Defaults to true when sortableId is set. */
  showDragHandle?: boolean;
}

// ---------------------------------------------------------------------------
// Internal: the interactive surface
// ---------------------------------------------------------------------------

interface RowSurfaceProps {
  prominence?: TableProminence;
  selected?: boolean;
  disabled?: boolean;
  onClick?: React.MouseEventHandler<HTMLTableRowElement>;
  children: React.ReactElement;
}

/** Wraps a body row in `Interactive.Stateful`; the header row as is. */
function RowSurface({
  prominence,
  selected,
  disabled,
  onClick,
  children,
}: RowSurfaceProps) {
  if (prominence === undefined) return children;
  return (
    <Interactive.Stateful
      variant="select-heavy"
      prominence={prominence}
      state={selected ? "selected" : "empty"}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </Interactive.Stateful>
  );
}

// ---------------------------------------------------------------------------
// Internal: sortable row
// ---------------------------------------------------------------------------

function SortableTableRow({
  sortableId,
  showDragHandle = true,
  prominence,
  selected,
  disabled,
  onClick,
  ref: _externalRef,
  children,
  ...props
}: TableRowProps) {
  const resolvedSize = useTableSize();
  const strings = useOpalStrings();

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
    <RowSurface
      prominence={prominence}
      selected={selected}
      disabled={disabled}
      onClick={onClick}
    >
      <tr
        ref={setNodeRef}
        style={style}
        className="tbl-row group/row"
        data-prominence={prominence}
        data-drag-handle={showDragHandle || undefined}
        data-selected={selected || undefined}
        data-disabled={disabled || undefined}
        onClick={prominence === undefined ? onClick : undefined}
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
                "absolute end-0 top-1/2 -translate-y-1/2 cursor-grab",
                "opacity-0 group-hover/row:opacity-100 transition-opacity",
                "flex items-center justify-center rounded-sm"
              )}
              aria-label={strings.dragToReorder}
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
    </RowSurface>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function TableRow({
  sortableId,
  showDragHandle,
  prominence,
  selected,
  disabled,
  onClick,
  ref,
  ...props
}: TableRowProps) {
  if (sortableId) {
    return (
      <SortableTableRow
        sortableId={sortableId}
        showDragHandle={showDragHandle}
        prominence={prominence}
        selected={selected}
        disabled={disabled}
        onClick={onClick}
        ref={ref}
        {...props}
      />
    );
  }

  return (
    <RowSurface
      prominence={prominence}
      selected={selected}
      disabled={disabled}
      onClick={onClick}
    >
      <tr
        ref={ref}
        className="tbl-row group/row"
        data-prominence={prominence}
        data-selected={selected || undefined}
        data-disabled={disabled || undefined}
        onClick={prominence === undefined ? onClick : undefined}
        {...props}
      />
    </RowSurface>
  );
}
