"use client";

import { useCallback, useMemo, useState } from "react";
import {
  Button,
  createTableColumns,
  EmptyMessageCard,
  Pagination,
  Table,
  Text,
} from "@opal/components";
import { localizeAndPrettify } from "@opal/time";
import Modal from "@/refresh-components/Modal";
import { Section } from "@/layouts/general-layouts";
import usePaginatedFetch from "@/hooks/usePaginatedFetch";
import { SWR_KEYS } from "@/lib/swr-keys";
import ExceptionTraceModal from "@/sections/modals/PreviewModal/ExceptionTraceModal";
import type { ExternalGroupSyncError } from "./types";

const ITEMS_PER_PAGE = 10;
const PAGES_PER_BATCH = 1;

const tc = createTableColumns<ExternalGroupSyncError>();

function buildColumns(onTraceClick: (trace: string) => void) {
  return [
    tc.column("time_created", {
      header: "Time",
      weight: 18,
      enableSorting: false,
      cell: (value) => (
        <Text as="span" font="main-ui-body" color="text-04">
          {localizeAndPrettify(value)}
        </Text>
      ),
    }),
    tc.column("external_group_name", {
      header: "Group",
      weight: 24,
      enableSorting: false,
      cell: (value, row) => (
        <Text as="span" font="main-ui-body" color="text-04" maxLines={2}>
          {value ?? row.external_group_id ?? "Unknown"}
        </Text>
      ),
    }),
    tc.column("error_type", {
      header: "Type",
      weight: 14,
      enableSorting: false,
      cell: (value) => (
        <Text as="span" font="secondary-body" color="text-03">
          {value ?? "-"}
        </Text>
      ),
    }),
    tc.column("failure_message", {
      header: "Error Message",
      weight: 34,
      enableSorting: false,
      cell: (value) => (
        <Text as="span" font="secondary-body" color="text-03" maxLines={3}>
          {value}
        </Text>
      ),
    }),
    tc.column("full_exception_trace", {
      header: "Trace",
      weight: 10,
      enableSorting: false,
      cell: (value, row) =>
        value ? (
          <Button
            size="sm"
            prominence="tertiary"
            onClick={() => onTraceClick(value)}
          >
            View
          </Button>
        ) : (
          <Text as="span" font="secondary-body" color="text-03">
            -
          </Text>
        ),
    }),
  ];
}

export interface ExternalGroupSyncErrorsModalProps {
  ccPairId: number;
  attemptId: number;
  onClose: () => void;
}

export default function ExternalGroupSyncErrorsModal({
  ccPairId,
  attemptId,
  onClose,
}: ExternalGroupSyncErrorsModalProps) {
  const [openTrace, setOpenTrace] = useState<string | null>(null);
  const handleTraceClick = useCallback(
    (trace: string) => setOpenTrace(trace),
    []
  );
  const columns = useMemo(
    () => buildColumns(handleTraceClick),
    [handleTraceClick]
  );

  const {
    currentPageData,
    isLoading,
    error,
    currentPage,
    totalPages,
    goToPage,
  } = usePaginatedFetch<ExternalGroupSyncError>({
    itemsPerPage: ITEMS_PER_PAGE,
    pagesPerBatch: PAGES_PER_BATCH,
    endpoint: SWR_KEYS.ccPairExternalGroupSyncAttemptErrors(
      ccPairId,
      attemptId
    ),
    disableUrlSync: true,
  });

  const errors = currentPageData ?? [];

  return (
    <>
      {openTrace !== null && (
        <ExceptionTraceModal
          onOutsideClick={() => setOpenTrace(null)}
          exceptionTrace={openTrace}
          title="Group Membership Sync Error Trace"
        />
      )}
      <Modal open onOpenChange={onClose}>
        <Modal.Content width="full" height="full">
          <Modal.Header
            title="Group Membership Sync Errors"
            onClose={onClose}
            height="fit"
          />
          <Modal.Body height="full">
            <Section gap={1} alignItems="stretch" height="full">
              <Text as="p" font="main-ui-body" color="text-03">
                These errors were recorded while syncing individual external
                groups for this run.
              </Text>

              {error ? (
                <EmptyMessageCard
                  sizePreset="main-ui"
                  title="Failed to load group sync errors"
                  description={error.message}
                />
              ) : isLoading && currentPageData === null ? (
                <EmptyMessageCard
                  sizePreset="main-ui"
                  title="Loading group sync errors"
                />
              ) : errors.length === 0 ? (
                <EmptyMessageCard
                  sizePreset="main-ui"
                  title="No group sync errors found"
                />
              ) : (
                <Section gap={0.75} alignItems="stretch" height="auto">
                  <Table
                    data={errors}
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
                        onChange={goToPage}
                      />
                    </Section>
                  )}
                </Section>
              )}
            </Section>
          </Modal.Body>
        </Modal.Content>
      </Modal>
    </>
  );
}
