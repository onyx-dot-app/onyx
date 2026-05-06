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
import type { DocPermissionSyncAttemptSnapshot } from "./types";

const ERROR_MODAL_TITLE = "Document Permission Sync Error";

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

// Weights are TanStack-relative; they sum to 100 here purely for
// readability. `Time Started` is bumped to 28 so `localizeAndPrettify`
// (e.g. "5/3/2026, 12:00:00 PM") stays on a single line at standard
// 800px-wide admin layouts; the difference is taken from `Status` and
// `Docs Synced`, which both render short content.
function buildColumns(onErrorClick: (errorMessage: string) => void) {
  return [
    tc.column("time_started", {
      header: "Time Started",
      weight: 28,
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
    tc.column("total_docs_synced", {
      header: "Docs Synced",
      weight: 12,
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
        title="No document permission sync attempts yet"
        description="Document-permission sync runs are scheduled in the background. They may take some time to appear — try refreshing in ~30 seconds."
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
