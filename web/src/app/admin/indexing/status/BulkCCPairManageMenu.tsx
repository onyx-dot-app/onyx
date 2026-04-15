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

interface CCPairInfoResponse {
  connector: {
    id: number;
  };
  credential: {
    id: number;
  };
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

async function updateCCPairStatus(
  ccPairId: number,
  status: ConnectorCredentialPairStatus
): Promise<void> {
  const response = await fetch(`/api/manage/admin/cc-pair/${ccPairId}/status`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ status }),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ||
        `Failed to update status for cc_pair ${ccPairId}`
    );
  }
}

function getEligibleStatuses(
  statuses: ConnectorIndexingStatusLite[],
  action: BulkAction
): ConnectorIndexingStatusLite[] {
  if (action === "pause") {
    return statuses.filter(
      (status) =>
        status.cc_pair_status !== ConnectorCredentialPairStatus.PAUSED &&
        status.cc_pair_status !== ConnectorCredentialPairStatus.DELETING
    );
  }

  if (action === "resume") {
    return statuses.filter(
      (status) =>
        status.cc_pair_status === ConnectorCredentialPairStatus.PAUSED ||
        status.cc_pair_status === ConnectorCredentialPairStatus.INVALID
    );
  }

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

function buildConfirmationMessage(
  action: BulkAction,
  totalCount: number,
  invalidResumeCount: number
) {
  let message = `Are you sure you want to ${action} ${totalCount} connector${
    totalCount === 1 ? "" : "s"
  } matching the current search and filters?`;

  if (action === "resume" && invalidResumeCount > 0) {
    message += `\n\nThis will also re-enable ${invalidResumeCount} invalid connector${
      invalidResumeCount === 1 ? "" : "s"
    }.`;
  }

  return message;
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

      const invalidResumeCount =
        action === "resume"
          ? eligibleStatuses.filter(
              (status) =>
                status.cc_pair_status === ConnectorCredentialPairStatus.INVALID
            ).length
          : 0;

      const confirmed = window.confirm(
        buildConfirmationMessage(
          action,
          eligibleStatuses.length,
          invalidResumeCount
        )
      );

      if (!confirmed) {
        return;
      }

      let successCount = 0;
      let failureCount = 0;

      for (const status of eligibleStatuses) {
        try {
          if (action === "pause") {
            await updateCCPairStatus(
              status.cc_pair_id,
              ConnectorCredentialPairStatus.PAUSED
            );
            successCount += 1;
            continue;
          }

          if (action === "resume") {
            await updateCCPairStatus(
              status.cc_pair_id,
              ConnectorCredentialPairStatus.ACTIVE
            );
            successCount += 1;
            continue;
          }

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

      if (failureCount > 0) {
        toast.warning(
          `Bulk ${action} finished: ${successCount} succeeded, ${failureCount} failed.`
        );
      } else {
        toast.success(
          `Bulk ${action} finished: ${successCount} succeeded.`
        );
      }

      onSuccess();
    } catch (error) {
      console.error(`Bulk ${action} failed`, error);
      toast.error(
        error instanceof Error ? error.message : `Bulk ${action} failed`
      );
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <div className={`relative ${isDisabled ? "opacity-50 pointer-events-none" : ""}`} ref={menuRef}>
      <Button
        icon={SvgSettings}
        prominence="tertiary"
        onClick={() => setIsOpen((prev) => !prev)}
      />

      {isOpen && (
        <div className="absolute right-0 mt-2 w-48 rounded-md border border-border bg-background shadow-lg z-50">
          <button
            className="w-full text-left px-3 py-2 text-sm hover:bg-accent"
            onClick={() => runBulkAction("pause")}
          >
            Bulk Pause
          </button>
          <button
            className="w-full text-left px-3 py-2 text-sm hover:bg-accent"
            onClick={() => runBulkAction("resume")}
          >
            Bulk Resume
          </button>
          <button
            className="w-full text-left px-3 py-2 text-sm hover:bg-accent"
            onClick={() => runBulkAction("reindex")}
          >
            Bulk Re-Index
          </button>
          <button
            className="w-full text-left px-3 py-2 text-sm text-red-600 hover:bg-accent"
            onClick={() => runBulkAction("delete")}
          >
            Bulk Delete
          </button>
        </div>
      )}
    </div>
  );
}