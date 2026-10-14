"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import useSWR, { mutate } from "swr";
import { setCCPairStatus } from "@/lib/ccPair";
import { buildCCPairInfoUrl } from "@/lib/connectors/utils";
import { ConnectorCredentialPairStatus } from "@/lib/connectors/types";
import type {
  CCPairFullInfo,
  CCPairRun,
  CCPairRunErrors,
  CCPairRunStatusGroup,
  CCPairRunsResponse,
} from "@/lib/connectors/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";

// ---------------------------------------------------------------------------
// useStatusChange
// ---------------------------------------------------------------------------

/** Pauses, resumes, or re-enables a cc-pair, confirming first when it is invalid. */
export function useStatusChange(ccPair: CCPairFullInfo | null) {
  const t = useTranslations("admin.connector");
  const [isUpdating, setIsUpdating] = useState(false);
  const [showConfirmModal, setShowConfirmModal] = useState(false);

  const updateStatus = async (newStatus: ConnectorCredentialPairStatus) => {
    if (!ccPair) return false;

    setIsUpdating(true);

    try {
      // Call the backend to update the status
      await setCCPairStatus(ccPair.id, newStatus);

      // Use mutate to revalidate the status on the backend
      await mutate(buildCCPairInfoUrl(ccPair.id));
    } catch (error) {
      console.error("Failed to update status", error);
    } finally {
      // Reset local updating state and button text after mutation
      setIsUpdating(false);
    }

    return true;
  };

  const handleStatusChange = async (
    newStatus: ConnectorCredentialPairStatus
  ) => {
    if (isUpdating || !ccPair) return false; // Prevent double-clicks or multiple requests

    if (
      ccPair.status === ConnectorCredentialPairStatus.INVALID &&
      newStatus === ConnectorCredentialPairStatus.ACTIVE
    ) {
      setShowConfirmModal(true);
      return false;
    } else {
      return await updateStatus(newStatus);
    }
  };

  const ConfirmModal =
    showConfirmModal && ccPair ? (
      <ConfirmEntityModal
        entityType={t("reEnableModal.entityType")}
        entityName={ccPair.name}
        onClose={() => setShowConfirmModal(false)}
        onSubmit={() => {
          setShowConfirmModal(false);
          updateStatus(ConnectorCredentialPairStatus.ACTIVE);
        }}
        additionalDetails={t("reEnableModal.additionalDetails")}
        actionButtonText={t("reEnableModal.actionButton.label")}
      />
    ) : null;

  return {
    handleStatusChange,
    isUpdating,
    ConfirmModal,
  };
}

// ---------------------------------------------------------------------------
// useActivityGroup
// ---------------------------------------------------------------------------

/** Which list of the connector page's activity panel a run sits in. */
export type ActivityGroup = "failures" | "errors" | "resolved";

/** How each group narrows the runs feed. Resolved errors can sit on a run of any status. */
const ACTIVITY_GROUP_QUERY: Record<
  ActivityGroup,
  {
    statusGroups: CCPairRunStatusGroup[] | null;
    errors: CCPairRunErrors | null;
  }
> = {
  failures: { statusGroups: ["failed"], errors: null },
  errors: {
    statusGroups: ["running", "succeeded", "canceled"],
    errors: "unresolved",
  },
  resolved: { statusGroups: null, errors: "resolved" },
};

const ACTIVITY_PAGE_SIZE = 20;
// The runs route refuses a larger page, so a group grows up to here.
const ACTIVITY_MAX_PAGE_SIZE = 50;

export interface ActivityGroupState {
  group: ActivityGroup;
  runs: CCPairRun[];
  /** Runs in the group, loaded or not. */
  total: number;
  loaded: boolean;
  failed: boolean;
  isLoading: boolean;
  /** More runs than shown, and room left to ask for them. */
  hasMore: boolean;
  more: () => void;
}

/** One activity group, polled while `enabled`. `more` grows it a page; a new search resets it. */
export function useActivityGroup(
  ccPairId: number,
  group: ActivityGroup,
  q: string,
  enabled: boolean,
  pollMs: number
): ActivityGroupState {
  const [limit, setLimit] = useState(ACTIVITY_PAGE_SIZE);
  const [limitFor, setLimitFor] = useState(q);
  if (limitFor !== q) {
    setLimitFor(q);
    setLimit(ACTIVITY_PAGE_SIZE);
  }
  const { data, error, isLoading } = useSWR<CCPairRunsResponse>(
    enabled
      ? SWR_KEYS.ccPairRuns(ccPairId, {
          pageNum: 0,
          pageSize: limit,
          since: null,
          kinds: null,
          q,
          ...ACTIVITY_GROUP_QUERY[group],
        })
      : null,
    errorHandlingFetcher,
    { refreshInterval: pollMs, keepPreviousData: true }
  );
  return {
    group,
    runs: data?.items ?? [],
    total: data?.total_items ?? 0,
    loaded: data !== undefined,
    failed: error !== undefined,
    isLoading,
    hasMore:
      data !== undefined &&
      data.total_items > data.items.length &&
      limit < ACTIVITY_MAX_PAGE_SIZE,
    more: () =>
      setLimit((current) =>
        Math.min(ACTIVITY_MAX_PAGE_SIZE, current + ACTIVITY_PAGE_SIZE)
      ),
  };
}
