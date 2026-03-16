import React from "react";
import { z } from "zod";
import { defineComponent, type ElementNode } from "@onyx/genui";
import Text from "@/refresh-components/texts/Text";

/**
 * Lightweight table renderer for GenUI.
 *
 * We don't use DataTable here because it requires TanStack column definitions
 * and typed data — overkill for LLM-generated tables. Instead we render a
 * simple HTML table styled with Onyx design tokens.
 */
export const tableComponent = defineComponent({
  name: "Table",
  description: "A data table with columns and rows",
  group: "Content",
  props: z.object({
    columns: z.array(z.string()).describe("Column header labels"),
    rows: z
      .array(z.array(z.unknown()))
      .describe("Row data as arrays of values"),
    compact: z.boolean().optional().describe("Use compact row height"),
  }),
  component: ({
    props,
  }: {
    props: {
      columns: string[];
      rows: unknown[][];
      compact?: boolean;
    };
  }) => {
    const cellPadding = props.compact ? "px-3 py-1.5" : "px-3 py-2.5";
    const columns = props.columns ?? [];
    const rows = props.rows ?? [];

    return (
      <div className="w-full overflow-x-auto rounded-12 border border-border-01">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-background-neutral-01">
              {columns.map((col, i) => (
                <th
                  key={i}
                  className={`${cellPadding} text-left border-b border-border-01`}
                >
                  <Text mainUiAction text03>
                    {col}
                  </Text>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIdx) => {
              // Defensive: row might not be an array if resolver
              // returned a rendered element or an object
              const cells = Array.isArray(row) ? row : [row];
              return (
                <tr
                  key={rowIdx}
                  className="border-b border-border-01 last:border-b-0"
                >
                  {cells.map((cell, cellIdx) => (
                    <td key={cellIdx} className={cellPadding}>
                      {renderCell(cell)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  },
});

function renderCell(cell: unknown): React.ReactNode {
  // If it's a rendered React element (from NodeRenderer), return it directly
  if (React.isValidElement(cell)) {
    return cell;
  }

  // Primitive values → text
  if (
    typeof cell === "string" ||
    typeof cell === "number" ||
    typeof cell === "boolean"
  ) {
    return (
      <Text mainContentBody text05>
        {String(cell)}
      </Text>
    );
  }

  return (
    <Text mainContentBody text03>
      —
    </Text>
  );
}
