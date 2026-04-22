"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@opal/components";
import { SvgSettings } from "@opal/icons";
import { toast } from "@/hooks/useToast";
import { IndexingStatusRequest } from "@/lib/types";

interface BulkCCPairManageMenuProps {
  filters: IndexingStatusRequest;
  enabled: boolean;
  onSuccess: () => void;
}

type BulkAction = "pause" | "resume" | "reindex" | "delete";
type BulkStatusAction = "pause" | "resume";
type BulkManageAction = "reindex" | "delete";

interface BulkCCPairStatusResponse {
  action: BulkStatusAction;
  matched_count: number;
  eligible_count: number;
  updated_count: number;
  skipped_count: number;
  skipped_reasons: Record<string, number>;
}

interface BulkCCPairManageResponse {
  action: BulkManageAction;
  matched_count: number;
  eligible_count: number;
  updated_count: number;
  skipped_count: number;
  skipped_reasons: Record<string, number>;
}

async function bulkUpdateCCPairStatus(
  action: BulkStatusAction,
  filters: IndexingStatusRequest
): Promise<BulkCCPairStatusResponse> {
  const response = await fetch("/api/manage/admin/connector/bulk/status", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      action,
      filters,
    }),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ||
        `Failed to bulk ${action} connectors matching the current filters`
    );
  }

  return response.json();
}

async function bulkManageCCPairs(
  action: BulkManageAction,
  filters: IndexingStatusRequest
): Promise<BulkCCPairManageResponse> {
  const response = await fetch("/api/manage/admin/connector/bulk/manage", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      action,
      filters,
    }),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ||
        `Failed to bulk ${action} connectors matching the current filters`
    );
  }

  return response.json();
}

function formatSkippedReasons(skippedReasons: Record<string, number>): string {
  const labels: Record<string, string> = {
    forbidden: "not editable",
    already_in_target_state: "already in target state",
    missing_cc_pair_status: "missing status",
    indexing_in_progress: "already indexing",
    not_eligible_for_action: "not eligible",
    missing_cc_pair: "missing connector pair",
    update_failed: "update failed",
  };

  return Object.entries(skippedReasons)
    .filter(([, count]) => count > 0)
    .map(([key, count]) => `${count} ${labels[key] ?? key}`)
    .join(", ");
}

function buildBulkStatusConfirmationMessage(action: BulkStatusAction) {
  return `Are you sure you want to bulk ${action} all editable connectors matching the current search and filters?`;
}

function buildBulkManageConfirmationMessage(action: BulkManageAction) {
  return `Are you sure you want to bulk ${action} all editable connectors matching the current search and filters?`;
}

export function BulkCCPairManageMenu({
  filters,
  enabled,
  onSuccess,
}: BulkCCPairManageMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function handleOutsideClick(event: MouseEvent) {
      if (!menuRef.current) return;
      if (!menuRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }

    document.addEventListener("mousedown", handleOutsideClick);
    return () => {
      document.removeEventListener("mousedown", handleOutsideClick);
    };
  }, []);

  const isDisabled = !enabled || isRunning;

  const runBulkAction = async (action: BulkAction) => {
    try {
      setIsOpen(false);
      setIsRunning(true);

      if (action === "pause" || action === "resume") {
        const confirmed = window.confirm(
          buildBulkStatusConfirmationMessage(action)
        );

        if (!confirmed) {
          return;
        }

        const result = await bulkUpdateCCPairStatus(action, filters);
        onSuccess();

        const skippedSummary = formatSkippedReasons(result.skipped_reasons);

        if (result.updated_count > 0) {
          toast.success(
            skippedSummary
              ? `Bulk ${action} complete: ${result.updated_count} updated, ${result.skipped_count} skipped (${skippedSummary}).`
              : `Bulk ${action} complete: ${result.updated_count} updated.`
          );
        } else {
          toast.error(
            skippedSummary
              ? `No connectors were updated for bulk ${action}. Skipped: ${skippedSummary}.`
              : `No connectors were updated for bulk ${action}.`
          );
        }

        return;
      }

      if (action === "delete") {
        const confirmed = window.confirm(
          buildBulkManageConfirmationMessage(action)
        );

        if (!confirmed) {
          return;
        }
      }

      const result = await bulkManageCCPairs(action, filters);
      onSuccess();

      const skippedSummary = formatSkippedReasons(result.skipped_reasons);
      const actionLabel = action === "reindex" ? "re-indexed" : "deleted";

      if (result.updated_count > 0) {
        toast.success(
          skippedSummary
            ? `Bulk ${action} complete: ${result.updated_count} ${actionLabel}, ${result.skipped_count} skipped (${skippedSummary}).`
            : `Bulk ${action} complete: ${result.updated_count} ${actionLabel}.`
        );
      } else {
        toast.error(
          skippedSummary
            ? `No connectors were ${actionLabel}. Skipped: ${skippedSummary}.`
            : `No connectors were ${actionLabel}.`
        );
      }
    } catch (error) {
      console.error(`Bulk action ${action} failed`, error);
      toast.error(
        error instanceof Error
          ? error.message
          : `Bulk ${action} failed unexpectedly`
      );
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <div ref={menuRef} className="relative">
      <div className={isDisabled ? "pointer-events-none opacity-50" : ""}>
        <Button
          icon={SvgSettings}
          onClick={() => {
            if (isDisabled) return;
            setIsOpen((prev) => !prev);
          }}
        >
          Bulk Manage
        </Button>
      </div>

      {isOpen && !isDisabled && (
        <div className="absolute right-0 z-20 mt-2 w-48 rounded-md border border-border bg-background shadow-lg">
          <button
            className="block w-full px-4 py-2 text-left text-sm hover:bg-accent-background"
            onClick={() => void runBulkAction("pause")}
          >
            Pause
          </button>

          <button
            className="block w-full px-4 py-2 text-left text-sm hover:bg-accent-background"
            onClick={() => void runBulkAction("resume")}
          >
            Resume
          </button>

          <button
            className="block w-full px-4 py-2 text-left text-sm hover:bg-accent-background"
            onClick={() => void runBulkAction("reindex")}
          >
            Re-Index
          </button>

          <button
            className="block w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-accent-background dark:text-red-400"
            onClick={() => void runBulkAction("delete")}
          >
            Delete
          </button>
        </div>
      )}
    </div>
  );
}