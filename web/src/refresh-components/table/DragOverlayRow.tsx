import { memo } from "react";
import { type Row, flexRender } from "@tanstack/react-table";
import TableRow from "@/refresh-components/table/TableRow";
import TableCell from "@/refresh-components/table/TableCell";
import QualifierContainer from "@/refresh-components/table/QualifierContainer";
import TableQualifier from "@/refresh-components/table/TableQualifier";
import ActionsContainer from "@/refresh-components/table/ActionsContainer";
import type {
  OnyxColumnDef,
  OnyxQualifierColumn,
} from "@/refresh-components/table/types";

interface DragOverlayRowProps<TData> {
  row: Row<TData>;
  variant?: "table" | "list";
  columnWidths?: Record<string, number>;
  columnKindMap?: Map<string, OnyxColumnDef<TData>>;
  qualifierColumn?: OnyxQualifierColumn<TData> | null;
  isSelectable?: boolean;
}

function DragOverlayRowInner<TData>({
  row,
  variant,
  columnWidths,
  columnKindMap,
  qualifierColumn,
  isSelectable = false,
}: DragOverlayRowProps<TData>) {
  const tableWidth = columnWidths
    ? Object.values(columnWidths).reduce((sum, w) => sum + w, 0)
    : undefined;

  return (
    <table
      className="border-collapse"
      style={{
        tableLayout: "fixed",
        ...(tableWidth != null ? { width: tableWidth } : { minWidth: "100%" }),
      }}
    >
      {columnWidths && (
        <colgroup>
          {row.getVisibleCells().map((cell) => (
            <col
              key={cell.column.id}
              style={{ width: columnWidths[cell.column.id] }}
            />
          ))}
        </colgroup>
      )}
      <tbody>
        <TableRow variant={variant} selected={row.getIsSelected()}>
          {row.getVisibleCells().map((cell) => {
            const colDef = columnKindMap?.get(cell.column.id);

            if (colDef?.kind === "qualifier" && qualifierColumn) {
              return (
                <QualifierContainer key={cell.id} type="cell">
                  <TableQualifier
                    content={qualifierColumn.content}
                    initials={qualifierColumn.getInitials?.(row.original)}
                    icon={qualifierColumn.getIcon?.(row.original)}
                    imageSrc={qualifierColumn.getImageSrc?.(row.original)}
                    selectable={isSelectable}
                    selected={isSelectable && row.getIsSelected()}
                  />
                </QualifierContainer>
              );
            }

            if (colDef?.kind === "actions") {
              return (
                <ActionsContainer key={cell.id} type="cell">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </ActionsContainer>
              );
            }

            return (
              <TableCell key={cell.id}>
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </TableCell>
            );
          })}
        </TableRow>
      </tbody>
    </table>
  );
}

const DragOverlayRow = memo(DragOverlayRowInner) as typeof DragOverlayRowInner;

export default DragOverlayRow;
export type { DragOverlayRowProps };
