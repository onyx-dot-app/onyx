import { memo } from "react";
import { type Row, flexRender } from "@tanstack/react-table";
import TableRow from "./TableRow";
import TableCell from "./TableCell";
import QualifierContainer from "./QualifierContainer";
import TableQualifier from "./TableQualifier";
import ActionsContainer from "./ActionsContainer";
import type { OnyxColumnDef, OnyxQualifierColumn } from "./types";

interface DragOverlayRowProps<TData> {
  row: Row<TData>;
  columnWidths?: Record<string, number>;
  columnKindMap?: Map<string, OnyxColumnDef<TData>>;
  qualifierColumn?: OnyxQualifierColumn<TData> | null;
  isSelectable?: boolean;
}

function DragOverlayRowInner<TData>({
  row,
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
        <TableRow selected={row.getIsSelected()}>
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
