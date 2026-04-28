"use client";

import { useMemo } from "react";
import { Table, createTableColumns } from "@opal/components";
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

// Inline right-aligned text. Opal's data columns don't expose a column-level
// alignment prop, so the cell renderer aligns its own content.
function RightCell({ children }: { children: React.ReactNode }) {
  return <span className="block w-full text-right">{children}</span>;
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

  // Sorting is driven externally via SortToggle, so disable per-column sort.
  const columns = useMemo(
    () => [
      tc.column("stage", {
        header: "Stage",
        weight: 28,
        enableSorting: false,
        cell: (_value, row) => <StageLabelCell stage={row.stage} />,
      }),
      tc.column("avg_duration_ms", {
        header: "Avg time",
        weight: 26,
        enableSorting: false,
        cell: (_value, row) => <AvgTimeCell stage={row} maxAvgMs={maxAvgMs} />,
      }),
      tc.column("total_duration_ms", {
        header: "Total time",
        weight: 12,
        enableSorting: false,
        cell: (value) => <RightCell>{formatDurationMs(value)}</RightCell>,
      }),
      tc.column("event_count", {
        header: "Calls",
        weight: 8,
        enableSorting: false,
        cell: (value) => <RightCell>{value}</RightCell>,
      }),
      tc.column("min_duration_ms", {
        header: "Min",
        weight: 10,
        enableSorting: false,
        cell: (value) => <RightCell>{formatOptionalMs(value)}</RightCell>,
      }),
      tc.column("max_duration_ms", {
        header: "Max",
        weight: 10,
        enableSorting: false,
        cell: (value) => <RightCell>{formatOptionalMs(value)}</RightCell>,
      }),
    ],
    [maxAvgMs]
  );

  return (
    <Table
      data={sorted}
      columns={columns}
      getRowId={(row) => row.stage}
      pageSize={Infinity}
      variant="rows"
    />
  );
}
