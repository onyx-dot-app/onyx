"use client";

import { useState } from "react";
import { Button, Text } from "@opal/components";
import { SvgHistory, SvgChevronDown, SvgTrash } from "@opal/icons";
import { cn } from "@opal/utils";
import Popover from "@/refresh-components/Popover";
import type { ReviewRun } from "@/app/proposal-review/types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatRunDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function statusDotColor(run: ReviewRun): string {
  if (run.status === "RUNNING" || run.status === "PENDING") {
    return "bg-theme-primary-03";
  }
  if (run.status === "FAILED") {
    return "bg-status-error-03";
  }
  if (run.failed_rules > 0) {
    return "bg-status-warning-03";
  }
  return "bg-status-success-03";
}

function statusLabel(run: ReviewRun): string {
  if (run.status === "RUNNING") return "Running";
  if (run.status === "PENDING") return "Pending";
  if (run.status === "FAILED") return "Failed";
  if (run.failed_rules > 0) {
    return `${run.total_rules - run.failed_rules}/${run.total_rules}`;
  }
  return `${run.total_rules} rules`;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface RunHistorySelectorProps {
  runs: ReviewRun[];
  selectedRunId: string | null;
  onSelectRun: (runId: string | null) => void;
  proposalId: string;
  onRunDeleted: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function RunHistorySelector({
  runs,
  selectedRunId,
  onSelectRun,
  proposalId,
  onRunDeleted,
}: RunHistorySelectorProps) {
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  const latestRun = runs[0] as ReviewRun | undefined;
  if (!latestRun) return null;

  const isViewingLatest =
    selectedRunId === null || selectedRunId === latestRun.id;
  const selectedRun = isViewingLatest
    ? latestRun
    : runs.find((r) => r.id === selectedRunId) ?? latestRun;

  async function handleDelete(run: ReviewRun, e: React.MouseEvent) {
    e.stopPropagation();
    if (run.status === "RUNNING") return;

    setDeleting(run.id);
    try {
      const res = await fetch(
        `/api/proposal-review/proposals/${proposalId}/review-runs/${run.id}`,
        { method: "DELETE" }
      );
      if (res.ok) {
        onRunDeleted();
        setOpen(false);
      }
    } finally {
      setDeleting(null);
    }
  }

  return (
    <div className="flex items-center px-4 py-1.5 border-b border-border-01 shrink-0">
      <Popover open={open} onOpenChange={setOpen}>
        <Popover.Trigger asChild>
          <button className="flex items-center gap-1.5 rounded-08 px-1.5 py-0.5 hover:bg-background-neutral-02 transition-colors">
            <SvgHistory className="h-3.5 w-3.5 text-text-02" />
            <Text font="secondary-body" color="text-03">
              {isViewingLatest
                ? `Latest run · ${formatRunDate(selectedRun.created_at)}`
                : formatRunDate(selectedRun.created_at)}
            </Text>
            <SvgChevronDown className="h-3 w-3 text-text-02" />
          </button>
        </Popover.Trigger>
        <Popover.Content width="xl" align="start" sideOffset={4}>
          <Popover.Menu>
            {runs.map((run, index) => {
              const isSelected =
                run.id === selectedRun.id &&
                (isViewingLatest ? index === 0 : true);
              const isRunning = run.status === "RUNNING";

              return (
                <Popover.Close asChild key={run.id}>
                  <button
                    className={cn(
                      "flex items-center gap-2 w-full px-2 py-1.5 rounded-08 text-left group",
                      "hover:bg-background-neutral-02 transition-colors",
                      isSelected && "bg-background-neutral-02"
                    )}
                    onClick={() => onSelectRun(index === 0 ? null : run.id)}
                  >
                    <div
                      className={cn(
                        "h-2 w-2 rounded-full shrink-0",
                        statusDotColor(run)
                      )}
                    />
                    <div className="flex-1 min-w-0">
                      <Text font="secondary-action" color="text-04">
                        {index === 0
                          ? `Latest · ${formatRunDate(run.created_at)}`
                          : formatRunDate(run.created_at)}
                      </Text>
                    </div>
                    <Text font="secondary-body" color="text-03">
                      {statusLabel(run)}
                    </Text>
                    {!isRunning && (
                      <div
                        className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                        onClick={(e) => handleDelete(run, e)}
                      >
                        <SvgTrash
                          className={cn(
                            "h-3.5 w-3.5 text-text-02 hover:text-action-danger-03 transition-colors",
                            deleting === run.id && "animate-pulse"
                          )}
                        />
                      </div>
                    )}
                  </button>
                </Popover.Close>
              );
            })}
          </Popover.Menu>
        </Popover.Content>
      </Popover>

      {!isViewingLatest && (
        <div className="ml-2">
          <Button
            variant="default"
            prominence="tertiary"
            size="2xs"
            onClick={() => onSelectRun(null)}
          >
            Back to latest
          </Button>
        </div>
      )}
    </div>
  );
}
