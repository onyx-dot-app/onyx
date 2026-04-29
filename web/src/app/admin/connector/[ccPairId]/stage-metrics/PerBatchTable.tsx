"use client";

import { useMemo } from "react";
import { Table, Text, createTableColumns } from "@opal/components";
import { IndexAttemptStageMetric } from "@/lib/types";
import { formatDurationMs } from "@/lib/time";
import { SortMode } from "./interfaces";
import { sortPerBatchStages } from "./utils";
import StageLabelCell from "./StageLabelCell";
import AvgTimeCell from "./AvgTimeCell";

interface PerBatchTableProps {
  perBatchStages: IndexAttemptStageMetric[];
  sortMode: SortMode;
}

const tc = createTableColumns<IndexAttemptStageMetric>();

// Plain left-aligned text cell. Matches the `secondary-body` font used by
// `StageLabelCell`/`AvgTimeCell` so all cells share the same type style.
function TextCell({ children }: { children: string | number }) {
  return (
    <Text font="secondary-body" color="text-05" nowrap>
      {String(children)}
    </Text>
  );
}

function formatOptionalMs(value: number | null): string {
  return value !== null ? formatDurationMs(value) : "—";
}

export default function PerBatchTable({
  perBatchStages,
  sortMode,
}: PerBatchTableProps) {
  const sorted = useMemo(
    () => sortPerBatchStages(perBatchStages, sortMode),
    [perBatchStages, sortMode]
  );

  // Used to scale the per-row average-time bar. Falls back to 0 when no
  // stage has an average yet, in which case rows render no bar at all.
  const maxAvgMs = useMemo(
    () =>
      sorted.reduce(
        (acc, s) =>
          s.avg_duration_ms !== null ? Math.max(acc, s.avg_duration_ms) : acc,
        0
      ),
    [sorted]
  );

  // Use displayColumn (rather than tc.column) to set explicit minWidths.
  // tc.column derives minWidth from header length only, which produces tight
  // columns that wrap stage labels like "Permission validation" or numeric
  // cells like "1.23s ± 456ms" onto a second line.
  const columns = useMemo(
    () => [
      tc.displayColumn({
        id: "stage",
        header: "Stage",
        width: { weight: 32, minWidth: 220 },
        cell: (row) => <StageLabelCell stage={row.stage} />,
      }),
      tc.displayColumn({
        id: "avg",
        header: "Avg time",
        // The Modal "lg" width minus body padding is ~768px. Other columns'
        // minWidths sum to 580, so capping avg at 170 keeps the total minWidth
        // under the modal's inner width and prevents a horizontal scrollbar.
        // The avg/std label only needs ~100px on a single line; the rest is
        // for the bar (which is `w-full` and shrinks freely).
        width: { weight: 30, minWidth: 170 },
        cell: (row) => <AvgTimeCell stage={row} maxAvgMs={maxAvgMs} />,
      }),
      tc.displayColumn({
        id: "total",
        header: "Total time",
        width: { weight: 14, minWidth: 110 },
        cell: (row) => (
          <TextCell>{formatDurationMs(row.total_duration_ms)}</TextCell>
        ),
      }),
      tc.displayColumn({
        id: "calls",
        header: "Calls",
        width: { weight: 8, minWidth: 70 },
        cell: (row) => <TextCell>{row.event_count}</TextCell>,
      }),
      tc.displayColumn({
        id: "min",
        header: "Min",
        width: { weight: 8, minWidth: 90 },
        cell: (row) => (
          <TextCell>{formatOptionalMs(row.min_duration_ms)}</TextCell>
        ),
      }),
      tc.displayColumn({
        id: "max",
        header: "Max",
        width: { weight: 8, minWidth: 90 },
        cell: (row) => (
          <TextCell>{formatOptionalMs(row.max_duration_ms)}</TextCell>
        ),
      }),
    ],
    [maxAvgMs]
  );

  // Use the default `cards` variant (matches the Agents page table) for
  // spacious, rounded-card rows rather than the boxy `rows` borders.
  // Intentionally omit `pageSize` and `footer`: Opal's `Table` then sets
  // its effective page size to `data.length`, which renders all rows in a
  // single page without pagination. Passing `pageSize: Infinity` instead
  // breaks TanStack's pagination row model (the `pageSize * pageIndex`
  // slice math evaluates to `NaN` and the body renders zero rows).
  return (
    <Table data={sorted} columns={columns} getRowId={(row) => row.stage} />
  );
}
