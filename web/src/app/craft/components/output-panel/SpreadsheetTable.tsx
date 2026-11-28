"use client";

import { memo } from "react";
import { Text } from "@opal/components";
import { cn } from "@opal/utils";

interface SpreadsheetTableProps {
  rows: string[][];
  framed?: boolean;
}

function SpreadsheetTableView({ rows, framed = true }: SpreadsheetTableProps) {
  return (
    <table
      className={cn(
        "w-full text-sm text-text-04 border-separate border-spacing-0",
        framed && "rounded-lg border border-border-01 overflow-hidden"
      )}
    >
      <thead className="sticky top-0 z-10 bg-background-neutral-02">
        <tr>
          {rows[0]?.map((cell, index) => (
            <th
              key={index}
              className="min-w-28 text-start font-medium px-3 py-2.5 border-b border-e last:border-e-0 border-border-01 whitespace-pre-wrap"
            >
              <Text font="secondary-action" color="text-04">
                {cell}
              </Text>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.slice(1).map((row, index) => (
          <tr
            key={index}
            className="group hover:bg-background-neutral-02 transition-colors"
          >
            {row.map((cell, column) => (
              <td
                key={column}
                className="px-3 py-2 border-b border-e last:border-e-0 group-last:border-b-0 border-border-01 whitespace-pre-wrap align-top"
              >
                <Text font="secondary-body" color="text-04">
                  {cell}
                </Text>
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export const SpreadsheetTable = memo(SpreadsheetTableView);
