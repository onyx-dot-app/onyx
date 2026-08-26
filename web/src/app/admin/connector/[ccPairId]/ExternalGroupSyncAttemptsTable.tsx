"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  createTableColumns,
  EmptyMessageCard,
  Pagination,
  Table,
  Text,
} from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { localizeAndPrettify } from "@opal/time";
import ExceptionTraceModal from "@/sections/modals/PreviewModal/ExceptionTraceModal";
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

/** Translated column headers threaded in from the calling component. */
interface ColumnHeaders {
  timeStarted: string;
  status: string;
  users: string;
  groups: string;
  memberships: string;
  errorMessage: string;
}

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
function buildColumns(
  onErrorClick: (errorMessage: string) => void,
  headers: ColumnHeaders
) {
  return [
    tc.column("time_started", {
      header: headers.timeStarted,
      weight: 26,
      enableSorting: false,
      cell: (value) => (
        <Text as="span" font="main-ui-body" color="text-04">
          {value ? localizeAndPrettify(value) : "-"}
        </Text>
      ),
    }),
    tc.column("status", {
      header: headers.status,
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
      header: headers.users,
      weight: 10,
      enableSorting: false,
      cell: (value) => (
        <Text as="span" font="main-ui-body" color="text-04">
          {String(value)}
        </Text>
      ),
    }),
    tc.column("total_groups_processed", {
      header: headers.groups,
      weight: 10,
      enableSorting: false,
      cell: (value) => (
        <Text as="span" font="main-ui-body" color="text-04">
          {String(value)}
        </Text>
      ),
    }),
    tc.column("total_group_memberships_synced", {
      header: headers.memberships,
      weight: 12,
      enableSorting: false,
      cell: (value) => (
        <Text as="span" font="main-ui-body" color="text-04">
          {String(value)}
        </Text>
      ),
    }),
    tc.column("error_message", {
      header: headers.errorMessage,
      weight: 28,
      enableSorting: false,
      cell: (value, row) => (
        <ErrorMessageCell
          errorMessage={value}
          modalContent={row.full_exception_trace ?? value}
          onErrorClick={onErrorClick}
        />
      ),
    }),
  ];
}

interface ErrorMessageCellProps {
  errorMessage: string | null;
  /**
   * Full content shown in `ExceptionTraceModal` on click — prefers the
   * traceback when present, otherwise falls back to the short
   * ``error_message``. Older attempts (pre-traceback-capture migration)
   * have ``full_exception_trace = null`` and gracefully degrade to the
   * single-line summary, matching `IndexAttemptsTable`'s behavior.
   */
  modalContent: string | null;
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
  modalContent,
  onErrorClick,
}: ErrorMessageCellProps) {
  const t = useTranslations("admin.connector");

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
      onClick={() => onErrorClick(modalContent ?? errorMessage)}
      aria-label={t("syncTables.errorCell.ariaLabel")}
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
  const t = useTranslations("admin.connector");
  const [openErrorMessage, setOpenErrorMessage] = useState<string | null>(null);
  const handleErrorClick = useCallback(
    (errorMessage: string) => setOpenErrorMessage(errorMessage),
    []
  );
  const columns = useMemo(
    () =>
      buildColumns(handleErrorClick, {
        timeStarted: t("groupMembershipTable.columns.timeStarted"),
        status: t("groupMembershipTable.columns.status"),
        users: t("groupMembershipTable.columns.users"),
        groups: t("groupMembershipTable.columns.groups"),
        memberships: t("groupMembershipTable.columns.memberships"),
        errorMessage: t("groupMembershipTable.columns.errorMessage"),
      }),
    [handleErrorClick, t]
  );

  if (!attempts.length) {
    return (
      <EmptyMessageCard
        sizePreset="main-ui"
        title={t("groupMembershipTable.empty.title")}
        description={t("groupMembershipTable.empty.description")}
      />
    );
  }

  return (
    <>
      {openErrorMessage !== null && (
        <ExceptionTraceModal
          onOutsideClick={() => setOpenErrorMessage(null)}
          exceptionTrace={openErrorMessage}
          title={t("groupMembershipTable.errorModal.title")}
        />
      )}

      <Section gap={3} alignItems="stretch" height="auto">
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
