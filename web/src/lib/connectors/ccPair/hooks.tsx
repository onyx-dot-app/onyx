"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import useSWR, { mutate } from "swr";
import usePaginatedFetch from "@/hooks/usePaginatedFetch";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { setCCPairStatus } from "@/lib/ccPair";
import { buildCCPairInfoUrl } from "@/lib/connectors/utils";
import { ConnectorCredentialPairStatus } from "@/lib/connectors/types";
import type {
  CCPairFullInfo,
  CCPairSyncAttemptsResponse,
} from "@/lib/connectors/types";
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
// useSyncAttemptsPaginatedFetch
// ---------------------------------------------------------------------------

/**
 * Thin wrapper around `usePaginatedFetch` that adapts the
 * `CCPairSyncAttemptsResponse` shape used by both per-cc-pair sync-attempt
 * endpoints (`/permission-sync-attempts` and
 * `/external-group-sync-attempts`).
 *
 * The standard `usePaginatedFetch` hook expects `{ items, total_items }`,
 * which is a strict subset of `CCPairSyncAttemptsResponse` — so the
 * underlying paginated fetch works against either endpoint without
 * modification, ignoring the extra `applicable` field on the wire.
 *
 * Surfacing `applicable` requires a separate read because
 * `usePaginatedFetch` does not expose the raw response. The applicability
 * value is invariant per (cc_pair, sync_kind), so a single SWR probe with
 * `page_size=1` is the cheapest correct way to read it. SWR's URL-keyed
 * cache shares the result across concurrent renders.
 *
 * @see plans/permission-sync-attempt-tabs.md (PR C, option B)
 */

const ATTEMPTS_REFRESH_INTERVAL_MS = 5000;

interface PaginatedItem {
  id: number | string;
}

export interface UseSyncAttemptsPaginatedFetchConfig {
  /**
   * Base API URL for the sync-attempts endpoint, without query params.
   * E.g. `/api/manage/admin/cc-pair/123/permission-sync-attempts`.
   * Should be sourced from `SWR_KEYS` so that any future `mutate()` callers
   * can target the same key.
   */
  endpoint: string;
  /**
   * SWR cache key for the applicability probe (the `?page_num=0&page_size=1`
   * read). Must be a `SWR_KEYS` entry so that callers wanting to force-refresh
   * the probe can do so without re-deriving the URL inline. See the
   * `ccPair*SyncAttemptsProbe` builders in `web/src/lib/swr-keys.ts`.
   */
  swrProbeKey: string;
  itemsPerPage: number;
  pagesPerBatch: number;
}

export interface UseSyncAttemptsPaginatedFetchReturn<T extends PaginatedItem> {
  /**
   * `null` while the applicability probe is in flight; `true`/`false`
   * once known. The two non-null values map to "render the table" vs
   * "render the not-applicable message" — they are NOT redundant with
   * `items.length === 0`, see `CCPairSyncAttemptsResponse`.
   */
  applicable: boolean | null;
  applicableError: Error | null;
  applicableIsLoading: boolean;

  // Standard pagination state, only meaningful when `applicable === true`.
  // The underlying endpoint short-circuits to `items=[], total_items=0`
  // when not applicable, so reading these in that state is harmless but
  // misleading — gate on `applicable` first.
  currentPageData: T[] | null;
  currentPage: number;
  totalPages: number;
  totalItems: number;
  goToPage: (page: number) => void;
  refresh: () => Promise<void>;
  isLoading: boolean;
  error: Error | null;
}

interface ApplicabilityProbeResponse {
  applicable: boolean;
}

export function useSyncAttemptsPaginatedFetch<T extends PaginatedItem>({
  endpoint,
  swrProbeKey,
  itemsPerPage,
  pagesPerBatch,
}: UseSyncAttemptsPaginatedFetchConfig): UseSyncAttemptsPaginatedFetchReturn<T> {
  const {
    data: probeData,
    error: probeError,
    isLoading: applicableIsLoading,
  } = useSWR<CCPairSyncAttemptsResponse<T> | ApplicabilityProbeResponse>(
    swrProbeKey,
    errorHandlingFetcher
  );

  const applicable = probeData ? probeData.applicable : null;

  // Once we know the source has no applicable sync, stop polling — the
  // backend will keep returning `applicable=false, items=[]` every 5s
  // for the rest of the session otherwise.
  const refreshIntervalInMs =
    applicable === false ? 0 : ATTEMPTS_REFRESH_INTERVAL_MS;

  const paginated = usePaginatedFetch<T>({
    endpoint,
    itemsPerPage,
    pagesPerBatch,
    refreshIntervalInMs,
  });

  return {
    applicable,
    applicableError: (probeError as Error | undefined) ?? null,
    applicableIsLoading,

    currentPageData: paginated.currentPageData,
    currentPage: paginated.currentPage,
    totalPages: paginated.totalPages,
    totalItems: paginated.totalItems,
    goToPage: paginated.goToPage,
    refresh: paginated.refresh,
    isLoading: paginated.isLoading,
    error: paginated.error,
  };
}
