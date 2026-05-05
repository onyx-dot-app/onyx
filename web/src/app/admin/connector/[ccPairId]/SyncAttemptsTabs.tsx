"use client";

import { useState } from "react";

import { MessageCard } from "@opal/components";

import { Section } from "@/layouts/general-layouts";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import Tabs from "@/refresh-components/Tabs";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { IndexAttemptSnapshot } from "@/lib/types";

import { DocPermissionSyncAttemptsTable } from "./DocPermissionSyncAttemptsTable";
import { ExternalGroupSyncAttemptsTable } from "./ExternalGroupSyncAttemptsTable";
import { IndexAttemptsTable } from "./IndexAttemptsTable";
import type {
  CCPairFullInfo,
  DocPermissionSyncAttemptSnapshot,
  ExternalGroupSyncAttemptSnapshot,
} from "./types";
import useSyncAttemptsPaginatedFetch from "./useSyncAttemptsPaginatedFetch";

/**
 * Three-way tabbed view of attempt history for a permission-synced
 * connector. Renders inside the existing "Advanced" collapsible on
 * `/admin/connector/[ccPairId]` (wired up in PR D).
 *
 * Tabs: `Indexing` | `Document Permissions` | `Group Membership`.
 *
 * - The `Indexing` tab is driven by data passed in from `page.tsx`. The
 *   page-level `usePaginatedFetch` is needed regardless (e.g. for
 *   `latestIndexAttempt[0]`), so duplicating the fetch inside this tab
 *   would be wasteful.
 * - The two permission-sync tabs each lazy-mount their own
 *   `useSyncAttemptsPaginatedFetch` hook. Radix `Tabs.Content` defaults
 *   to unmounting inactive tabs, so a hook for an inactive tab does not
 *   fire — fetches happen only when the user opens that tab.
 *
 * For the two permission-sync tabs, the body's render path is:
 *
 *   probe loading           → spinner
 *   probe error             → `MessageCard` (error)
 *   `applicable === false`  → `MessageCard` (info, "no separate ... job")
 *   first page loading      → spinner
 *   page error              → `MessageCard` (error)
 *   no attempts             → empty-state `MessageCard` rendered by the
 *                              table component itself
 *   attempts present        → table with pagination
 */

const ITEMS_PER_PAGE = 8;
const PAGES_PER_BATCH = 4;

const NOT_APPLICABLE_DOC_PERMISSIONS_MESSAGE =
  "This connector does not use a separate document-permission syncing job.";

const NOT_APPLICABLE_GROUP_MEMBERSHIP_MESSAGE =
  "This connector does not use a separate group-membership syncing job.";

enum SyncAttemptsTab {
  INDEXING = "indexing",
  DOC_PERMISSIONS = "doc_permissions",
  GROUP_MEMBERSHIP = "group_membership",
}

export interface SyncAttemptsTabsProps {
  ccPair: CCPairFullInfo;
  /**
   * Indexing-tab data is owned by the parent page (which also reads
   * `indexAttempts[0]` for header-card status). The tab simply renders
   * what it's given so we don't double-fetch the indexing endpoint.
   */
  indexAttempts: IndexAttemptSnapshot[];
  indexCurrentPage: number;
  indexTotalPages: number;
  onIndexPageChange: (page: number) => void;
}

export function SyncAttemptsTabs({
  ccPair,
  indexAttempts,
  indexCurrentPage,
  indexTotalPages,
  onIndexPageChange,
}: SyncAttemptsTabsProps) {
  const [tab, setTab] = useState<SyncAttemptsTab>(SyncAttemptsTab.INDEXING);

  return (
    <Tabs
      value={tab}
      onValueChange={(value) => setTab(value as SyncAttemptsTab)}
    >
      <Tabs.List variant="contained">
        <Tabs.Trigger value={SyncAttemptsTab.INDEXING}>Indexing</Tabs.Trigger>
        <Tabs.Trigger value={SyncAttemptsTab.DOC_PERMISSIONS}>
          Document Permissions
        </Tabs.Trigger>
        <Tabs.Trigger value={SyncAttemptsTab.GROUP_MEMBERSHIP}>
          Group Membership
        </Tabs.Trigger>
      </Tabs.List>

      <Tabs.Content value={SyncAttemptsTab.INDEXING}>
        <IndexAttemptsTable
          ccPair={ccPair}
          indexAttempts={indexAttempts}
          currentPage={indexCurrentPage}
          totalPages={indexTotalPages}
          onPageChange={onIndexPageChange}
        />
      </Tabs.Content>

      <Tabs.Content value={SyncAttemptsTab.DOC_PERMISSIONS}>
        <DocPermissionsTabBody ccPairId={ccPair.id} />
      </Tabs.Content>

      <Tabs.Content value={SyncAttemptsTab.GROUP_MEMBERSHIP}>
        <GroupMembershipTabBody ccPairId={ccPair.id} />
      </Tabs.Content>
    </Tabs>
  );
}

function DocPermissionsTabBody({ ccPairId }: { ccPairId: number }) {
  const result =
    useSyncAttemptsPaginatedFetch<DocPermissionSyncAttemptSnapshot>({
      endpoint: SWR_KEYS.ccPairPermissionSyncAttempts(ccPairId),
      swrProbeKey: SWR_KEYS.ccPairPermissionSyncAttemptsProbe(ccPairId),
      itemsPerPage: ITEMS_PER_PAGE,
      pagesPerBatch: PAGES_PER_BATCH,
    });

  const gate = renderTabGate(result, NOT_APPLICABLE_DOC_PERMISSIONS_MESSAGE);
  if (gate !== null) return gate;

  return (
    <DocPermissionSyncAttemptsTable
      attempts={result.currentPageData ?? []}
      currentPage={result.currentPage}
      totalPages={result.totalPages}
      onPageChange={result.goToPage}
    />
  );
}

function GroupMembershipTabBody({ ccPairId }: { ccPairId: number }) {
  const result =
    useSyncAttemptsPaginatedFetch<ExternalGroupSyncAttemptSnapshot>({
      endpoint: SWR_KEYS.ccPairExternalGroupSyncAttempts(ccPairId),
      swrProbeKey: SWR_KEYS.ccPairExternalGroupSyncAttemptsProbe(ccPairId),
      itemsPerPage: ITEMS_PER_PAGE,
      pagesPerBatch: PAGES_PER_BATCH,
    });

  const gate = renderTabGate(result, NOT_APPLICABLE_GROUP_MEMBERSHIP_MESSAGE);
  if (gate !== null) return gate;

  return (
    <ExternalGroupSyncAttemptsTable
      attempts={result.currentPageData ?? []}
      currentPage={result.currentPage}
      totalPages={result.totalPages}
      onPageChange={result.goToPage}
    />
  );
}

interface TabGateInputs {
  applicable: boolean | null;
  applicableIsLoading: boolean;
  applicableError: Error | null;
  isLoading: boolean;
  error: Error | null;
  currentPageData: unknown[] | null;
}

/**
 * Compresses the loading / error / not-applicable / first-page-loading
 * branches both permission-sync tabs share into one place. Returns
 * `null` when the caller should render its own table.
 */
function renderTabGate(
  inputs: TabGateInputs,
  notApplicableMessage: string
): React.ReactElement | null {
  const {
    applicable,
    applicableIsLoading,
    applicableError,
    isLoading,
    error,
    currentPageData,
  } = inputs;

  if (applicableError) {
    return (
      <MessageCard
        variant="error"
        title="Failed to load sync attempts"
        description={applicableError.message}
      />
    );
  }
  if (applicableIsLoading || applicable === null) {
    return <SyncAttemptsTabSpinner />;
  }
  if (applicable === false) {
    return (
      <MessageCard
        variant="info"
        title="Not applicable"
        description={notApplicableMessage}
      />
    );
  }
  if (isLoading && currentPageData === null) {
    return <SyncAttemptsTabSpinner />;
  }
  if (error) {
    return (
      <MessageCard
        variant="error"
        title="Failed to load sync attempts"
        description={error.message}
      />
    );
  }
  return null;
}

function SyncAttemptsTabSpinner() {
  return (
    <Section
      flexDirection="row"
      justifyContent="center"
      alignItems="center"
      height="auto"
      className="py-6"
    >
      <SimpleLoader className="h-6 w-6" />
    </Section>
  );
}
