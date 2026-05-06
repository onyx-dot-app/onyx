"use client";

import { useCallback, useMemo, useState } from "react";
import {
  createTableColumns,
  EmptyMessageCard,
  Pagination,
  Table,
  Text,
} from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { localizeAndPrettify } from "@/lib/time";
import ExceptionTraceModal from "@/sections/modals/PreviewModal/ExceptionTraceModal";
import { PermissionSyncStatusBadge } from "./PermissionSyncStatusBadge";
import type { ExternalGroupSyncAttemptSnapshot } from "./types";

const ERROR_MODAL_TITLE = "Group Membership Sync Error";

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

// Headers are intentionally short ("Users", not "Users Processed").
// Opal's `TableHead` renders headers via `String(children)` (see
// `web/lib/opal/src/components/table/TableHead.tsx:96`), which kills any
// rich-content header (Tooltip + info icon, etc.) — so we lean on
// concise, contextually-clear labels instead. The tab itself is named
// "Group Membership", so "Users / Groups / Memberships" reads as
// "users seen / groups processed / memberships written" without
// further annotation.
//
// Weights are TanStack-relative; the per-column `minWidth =
// header.length * 8 + 40` floor means short labels are also necessary
// to actually achieve "skinnier" columns — e.g. "Users Processed"
// pins minWidth to 160px no matter the weight.
//
// `Time Started` is bumped to 26 so `localizeAndPrettify` (e.g.
// "5/3/2026, 12:00:00 PM") stays on a single line.
function buildColumns(onErrorClick: (errorMessage: string) => void) {
  return [
    tc.column("time_started", {
      header: "Time Started",
      weight: 26,
      enableSorting: false,
      cell: (value) => (
        <Text as="span" font="main-ui-body" color="text-04">
          {value ? localizeAndPrettify(value) : "-"}
        </Text>
      ),
    }),
    tc.column("status", {
      header: "Status",
      weight: 14,
      enableSorting: false,
      cell: (value, row) => (
        <PermissionSyncStatusBadge
          status={value}
          errorMsg={row.error_message}
        />
      ),
    }),
    tc.column("total_users_processed", {
      header: "Users",
      weight: 10,
      enableSorting: false,
      cell: (value) => (
        <Text as="span" font="main-ui-body" color="text-04">
          {String(value)}
        </Text>
      ),
    }),
    tc.column("total_groups_processed", {
      header: "Groups",
      weight: 10,
      enableSorting: false,
      cell: (value) => (
        <Text as="span" font="main-ui-body" color="text-04">
          {String(value)}
        </Text>
      ),
    }),
    tc.column("total_group_memberships_synced", {
      header: "Memberships",
      weight: 12,
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
        <ErrorMessageCell errorMessage={value} onErrorClick={onErrorClick} />
      ),
    }),
  ];
}

interface ErrorMessageCellProps {
  errorMessage: string | null;
  onErrorClick: (errorMessage: string) => void;
}

/**
 * Renders the truncated error message as a clickable button when a
 * message is present, opening the `ExceptionTraceModal` on click.
 * Mirrors the row-level click affordance in `IndexAttemptsTable`,
 * scoped here to just the cell so the status-badge tooltip on the
 * left stays its own independent affordance.
 */
function ErrorMessageCell({
  errorMessage,
  onErrorClick,
}: ErrorMessageCellProps) {
  if (!errorMessage) {
    return (
      <Text as="span" font="secondary-body" color="text-03">
        -
      </Text>
    );
  }
  return (
    <button
      type="button"
      onClick={() => onErrorClick(errorMessage)}
      aria-label="View full error message"
      className="text-left w-full cursor-pointer hover:underline"
    >
      <Text as="span" font="secondary-body" color="text-03" maxLines={2}>
        {errorMessage}
      </Text>
    </button>
  );
}

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
  const [openErrorMessage, setOpenErrorMessage] = useState<string | null>(null);
  const handleErrorClick = useCallback(
    (errorMessage: string) => setOpenErrorMessage(errorMessage),
    []
  );
  const columns = useMemo(
    () => buildColumns(handleErrorClick),
    [handleErrorClick]
  );

  if (!attempts.length) {
    return (
      <EmptyMessageCard
        sizePreset="main-ui"
        title="No group membership sync attempts yet"
        description="Group-membership sync runs are scheduled in the background. They may take some time to appear — try refreshing in ~30 seconds."
      />
    );
  }

  return (
    <>
      {openErrorMessage !== null && (
        <ExceptionTraceModal
          onOutsideClick={() => setOpenErrorMessage(null)}
          exceptionTrace={openErrorMessage}
          title={ERROR_MODAL_TITLE}
        />
      )}

      <Section gap={0.75} alignItems="stretch" height="auto">
        <Table
          data={attempts}
          columns={columns}
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
    </>
  );
}
