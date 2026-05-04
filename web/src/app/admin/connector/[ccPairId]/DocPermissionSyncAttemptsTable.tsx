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
import type { DocPermissionSyncAttemptSnapshot } from "./types";

/**
 * Renders one page of `DocPermissionSyncAttempt` rows for the
 * connector-detail "Document Permissions" tab.
 *
 * Pagination is **driven externally** — the parent owns the SWR /
 * `usePaginatedFetch` state and passes the current page slice in. This
 * mirrors `IndexAttemptsTable`'s API so `SyncAttemptsTabs` (PR C) can
 * wire all three tables uniformly.
 *
 * Empty state ("no attempts yet but the sync IS applicable") is
 * distinct from the not-applicable state, which is rendered higher up
 * by `SyncAttemptsTabs` and never reaches this component. We render a
 * neutral `MessageCard` here only when `attempts.length === 0` AND the
 * caller has decided this tab is applicable.
 */

const tc = createTableColumns<DocPermissionSyncAttemptSnapshot>();

const COLUMNS = [
  tc.column("time_started", {
    header: "Time Started",
    weight: 22,
    enableSorting: false,
    cell: (value) => (
      <Text as="span" font="main-ui-body" color="text-04">
        {value ? localizeAndPrettify(value) : "-"}
      </Text>
    ),
  }),
  tc.column("status", {
    header: "Status",
    weight: 18,
    enableSorting: false,
    cell: (value, row) => (
      <PermissionSyncStatusBadge status={value} errorMsg={row.error_message} />
    ),
  }),
  tc.column("total_docs_synced", {
    header: "Docs Synced",
    weight: 14,
    enableSorting: false,
    cell: (value) => (
      <Text as="span" font="main-ui-body" color="text-04">
        {String(value)}
      </Text>
    ),
  }),
  tc.column("docs_with_permission_errors", {
    header: "Permission Errors",
    weight: 18,
    enableSorting: false,
    cell: (value) => (
      <Text as="span" font="main-ui-body" color="text-04">
        {String(value)}
      </Text>
    ),
  }),
  tc.column("error_message", {
    header: "Error Message",
    weight: 28,
    enableSorting: false,
    cell: (value) => (
      <Text as="span" font="secondary-body" color="text-03" maxLines={2}>
        {value ?? "-"}
      </Text>
    ),
  }),
];

export interface DocPermissionSyncAttemptsTableProps {
  attempts: DocPermissionSyncAttemptSnapshot[];
  /** 1-based page index, matching `IndexAttemptsTable`. */
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

export function DocPermissionSyncAttemptsTable({
  attempts,
  currentPage,
  totalPages,
  onPageChange,
}: DocPermissionSyncAttemptsTableProps) {
  if (!attempts.length) {
    return (
      <MessageCard
        variant="info"
        title="No document permission sync attempts scheduled yet"
        description="Document-permission sync runs are scheduled in the background. They may take some time to appear — try refreshing in ~30 seconds."
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
