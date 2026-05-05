"use client";

import {
  createTableColumns,
  MessageCard,
  Pagination,
  Table,
  Text,
} from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { localizeAndPrettify } from "@/lib/time";
import { PermissionSyncStatusBadge } from "./PermissionSyncStatusBadge";
import type { ExternalGroupSyncAttemptSnapshot } from "./types";

/**
 * Renders one page of `ExternalGroupPermissionSyncAttempt` rows for the
 * connector-detail "Group Membership" tab.
 *
 * Pagination is driven externally (parent owns the SWR /
 * `usePaginatedFetch` state), matching the `IndexAttemptsTable` and
 * `DocPermissionSyncAttemptsTable` shape so all three tables can be
 * mounted uniformly inside `SyncAttemptsTabs` (PR C).
 *
 * Note on row attribution for cc-pair-agnostic sources (Confluence,
 * Jira): the backend's `external-group-sync-attempts` endpoint widens
 * its query to all sibling cc-pairs of the same source for these
 * sources, so a row shown here may have been triggered against a
 * **different** cc-pair than the one being viewed. That's intentional
 * — a single source-wide group sync run logically applies to every
 * cc-pair sharing the source. See
 * `get_relevant_external_group_sync_attempts_for_cc_pair` in
 * `backend/onyx/db/permission_sync_attempt.py` for the resolution
 * rules and the multi-instance caveat.
 */

const tc = createTableColumns<ExternalGroupSyncAttemptSnapshot>();

const COLUMNS = [
  tc.column("time_started", {
    header: "Time Started",
    weight: 20,
    enableSorting: false,
    cell: (value) => (
      <Text as="span" font="main-ui-body" color="text-04">
        {value ? localizeAndPrettify(value) : "-"}
      </Text>
    ),
  }),
  tc.column("status", {
    header: "Status",
    weight: 16,
    enableSorting: false,
    cell: (value, row) => (
      <PermissionSyncStatusBadge status={value} errorMsg={row.error_message} />
    ),
  }),
  tc.column("total_users_processed", {
    header: "Users Processed",
    weight: 14,
    enableSorting: false,
    cell: (value) => (
      <Text as="span" font="main-ui-body" color="text-04">
        {String(value)}
      </Text>
    ),
  }),
  tc.column("total_groups_processed", {
    header: "Groups Processed",
    weight: 14,
    enableSorting: false,
    cell: (value) => (
      <Text as="span" font="main-ui-body" color="text-04">
        {String(value)}
      </Text>
    ),
  }),
  tc.column("total_group_memberships_synced", {
    header: "Memberships Synced",
    weight: 14,
    enableSorting: false,
    cell: (value) => (
      <Text as="span" font="main-ui-body" color="text-04">
        {String(value)}
      </Text>
    ),
  }),
  tc.column("error_message", {
    header: "Error Message",
    weight: 22,
    enableSorting: false,
    cell: (value) => (
      <Text as="span" font="secondary-body" color="text-03" maxLines={2}>
        {value ?? "-"}
      </Text>
    ),
  }),
];

export interface ExternalGroupSyncAttemptsTableProps {
  attempts: ExternalGroupSyncAttemptSnapshot[];
  /** 1-based page index, matching `IndexAttemptsTable`. */
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

export function ExternalGroupSyncAttemptsTable({
  attempts,
  currentPage,
  totalPages,
  onPageChange,
}: ExternalGroupSyncAttemptsTableProps) {
  if (!attempts.length) {
    return (
      <MessageCard
        variant="info"
        title="No group membership sync attempts scheduled yet"
        description="Group-membership sync runs are scheduled in the background. They may take some time to appear — try refreshing in ~30 seconds."
      />
    );
  }

  return (
    <Section gap={0.75} alignItems="stretch" height="auto">
      <Table
        data={attempts}
        columns={COLUMNS}
        getRowId={(row) => String(row.id)}
      />
      {totalPages > 1 && (
        <Section
          flexDirection="row"
          justifyContent="center"
          height="auto"
          className="pt-1"
        >
          <Pagination
            variant="list"
            currentPage={currentPage}
            totalPages={totalPages}
            onChange={onPageChange}
          />
        </Section>
      )}
    </Section>
  );
}
