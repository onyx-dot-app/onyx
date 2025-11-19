import React from "react";
import {
  Table,
  TableRow,
  TableHead,
  TableBody,
  TableCell,
  TableHeader,
} from "@/components/ui/table";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";

// Staggered loading animation skeleton with proper table column alignment
export function ConnectorStaggeredSkeleton({
  rowCount = 5,
  standalone = false,
  height = "h-20",
}: {
  rowCount?: number;
  standalone?: boolean; // if you want to show skeleton which is not in a table, set this to true
  height?: string;
}) {
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  const skeletonRows = [...Array(rowCount)].map((_, index) => (
    <TableRow
      key={index}
      className={`border border-border dark:border-neutral-700 hover:bg-accent-background animate-pulse ${height}`}
      style={{
        animationDelay: `${index * 150}ms`,
        animationDuration: "1.5s",
      }}
    >
      {/* Connector Name */}
      <TableCell>
        <div className="flex items-center gap-2">
          <div className="h-5 w-5 bg-neutral-200 dark:bg-neutral-700 rounded"></div>
          <div className="lg:w-[180px] xl:w-[350px] h-5 bg-neutral-200 dark:bg-neutral-700 rounded"></div>
        </div>
      </TableCell>

      {/* Last Success */}
      <TableCell>
        <div className="flex flex-col gap-1">
          <div className="h-3 w-20 bg-neutral-200 dark:bg-neutral-700 rounded"></div>
          <div className="h-4 w-16 bg-neutral-200 dark:bg-neutral-700 rounded"></div>
        </div>
      </TableCell>

      {/* Status */}
      <TableCell>
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 bg-neutral-200 dark:bg-neutral-700 rounded-full"></div>
          <div className="h-6 w-24 bg-neutral-200 dark:bg-neutral-700 rounded-full"></div>
        </div>
      </TableCell>

      {/* Access Type (Enterprise only) */}
      {isPaidEnterpriseFeaturesEnabled && (
        <TableCell>
          <div className="flex items-center gap-2">
            <div className="h-4 w-4 bg-neutral-200 dark:bg-neutral-700 rounded"></div>
            <div className="h-6 w-28 bg-neutral-200 dark:bg-neutral-700 rounded-full"></div>
          </div>
        </TableCell>
      )}

      {/* Docs Indexed */}
      <TableCell>
        <div className="flex flex-col gap-1">
          <div className="h-3 w-8 bg-neutral-200 dark:bg-neutral-700 rounded"></div>
          <div className="h-5 w-16 bg-neutral-200 dark:bg-neutral-700 rounded"></div>
        </div>
      </TableCell>

      {/* Settings Icon */}
      <TableCell>
        <div className="flex items-center justify-center">
          <div className="h-5 w-5 bg-neutral-200 dark:bg-neutral-700 rounded"></div>
        </div>
      </TableCell>
    </TableRow>
  ));

  // If standalone, wrap in complete table structure
  if (standalone) {
    return (
      <div className="w-full">
        <Table className="w-full">
          <TableBody>{skeletonRows}</TableBody>
        </Table>
      </div>
    );
  }

  // If not standalone, just return the rows
  return <>{skeletonRows}</>;
}
