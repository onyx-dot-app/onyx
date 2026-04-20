"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@opal/components";
import { SvgSettings } from "@opal/icons";
import { toast } from "@/hooks/useToast";
import { fetchConnectorIndexingStatus } from "@/lib/hooks";
import { runConnector } from "@/lib/connector";
import { scheduleDeletionJobForConnector } from "@/lib/documentDeletion";
import {
  ConnectorIndexingStatusLite,
  IndexingStatusRequest,
} from "@/lib/types";
import { ConnectorCredentialPairStatus } from "@/app/admin/connector/[ccPairId]/types";

interface BulkCCPairManageMenuProps {
  filters: IndexingStatusRequest;
  enabled: boolean;
  onSuccess: () => void;
}

type BulkAction = "pause" | "resume" | "reindex" | "delete";
type BulkStatusAction = "pause" | "resume";

interface CCPairInfoResponse {
  connector: {
    id: number;
  };
  credential: {
    id: number;
  };
}

interface BulkCCPairStatusResponse {
  action: BulkStatusAction;
  matched_count: number;
  eligible_count: number;
  updated_count: number;
  skipped_count: number;
  skipped_reasons: Record<string, number>;
}

function isConnectorStatus(
  item: ConnectorIndexingStatusLite | { id: number; source: string; name: string }
): item is ConnectorIndexingStatusLite {
  return "cc_pair_id" in item;
}

async function fetchCCPairInfo(
  ccPairId: number
): Promise<{ connectorId: number; credentialId: number }> {
  const response = await fetch(`/api/manage/admin/cc-pair/${ccPairId}`);

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ||
        `Failed to fetch connector info for cc_pair ${ccPairId}`
    );
  }

  const data: CCPairInfoResponse = await response.json();

  return {
    connectorId: data.connector.id,
    credentialId: data.credential.id,
  };
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

function getEligibleStatuses(
  statuses: ConnectorIndexingStatusLite[],
  action: "reindex" | "delete"
): ConnectorIndexingStatusLite[] {
  if (action === "reindex") {
    return statuses.filter(
      (status) =>
        !status.in_progress &&
        status.cc_pair_status !== ConnectorCredentialPairStatus.PAUSED &&
        status.cc_pair_status !== ConnectorCredentialPairStatus.INVALID &&
        status.cc_pair_status !== ConnectorCredentialPairStatus.DELETING
    );
  }

  return statuses.filter(
    (status) =>
      status.cc_pair_status !== ConnectorCredentialPairStatus.DELETING
  );
}

function formatSkippedReasons(skippedReasons: Record<string, number>): string {
  const labels: Record<string, string> = {
    forbidden: "not editable",
    already_in_target_state: "already in target state",
    missing_cc_pair_status: "missing status",
    not_eligible_for_action: "not eligible",
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

function buildConfirmationMessage(
  action: "reindex" | "delete",
  totalCount: number
) {
  return `Are you sure you want to ${action} ${totalCount} connector${
    totalCount === 1 ? "" : "s"
  } matching the current search and filters?`;
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

      const allResults = await fetchConnectorIndexingStatus({
        ...filters,
        get_all_connectors: true,
      });

      const allEditableStatuses = allResults
        .flatMap((group) => group.indexing_statuses)
        .filter(isConnectorStatus)
        .filter((status) => status.is_editable);

      const eligibleStatuses = getEligibleStatuses(allEditableStatuses, action);

      if (eligibleStatuses.length === 0) {
        toast.error(
          `No eligible connectors match the current search and filters for bulk ${action}.`
        );
        return;
      }

      const confirmed = window.confirm(
        buildConfirmationMessage(action, eligibleStatuses.length)
      );

      if (!confirmed) {
        return;
      }

      let successCount = 0;
      let failureCount = 0;

      for (const status of eligibleStatuses) {
        try {
          if (action === "reindex") {
            const { connectorId, credentialId } = await fetchCCPairInfo(
              status.cc_pair_id
            );
            const errorMsg = await runConnector(
              connectorId,
              [credentialId],
              false
            );

            if (errorMsg) {
              throw new Error(errorMsg);
            }

            successCount += 1;
            continue;
          }

          if (action === "delete") {
            const { connectorId, credentialId } = await fetchCCPairInfo(
              status.cc_pair_id
            );
            const errorMsg = await scheduleDeletionJobForConnector(
              connectorId,
              credentialId
            );

            if (errorMsg) {
              throw new Error(errorMsg);
            }

            successCount += 1;
            continue;
          }
        } catch (error) {
          console.error(
            `Bulk ${action} failed for cc_pair ${status.cc_pair_id}`,
            error
          );
          failureCount += 1;
        }
      }

      if (successCount > 0) {
        onSuccess();
        toast.success(
          `Bulk ${action} complete: ${successCount} succeeded${
            failureCount > 0 ? `, ${failureCount} failed` : ""
          }.`
        );
      } else {
        toast.error(`Bulk ${action} failed for all eligible connectors.`);
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
      <Button
        icon={SvgSettings}
        onClick={() => setIsOpen((prev) => !prev)}
        disabled={isDisabled}
      >
        Bulk Manage
      </Button>

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