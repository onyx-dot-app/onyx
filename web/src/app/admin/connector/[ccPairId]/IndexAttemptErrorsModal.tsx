"use client";

import { useCallback, useMemo, useRef } from "react";
import { createTableColumns, Pagination, Table, Text } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import { IndexAttemptError } from "./types";
import { localizeAndPrettify } from "@/lib/time";
import { SvgAlertTriangle } from "@opal/icons";

const ROW_HEIGHT = 65; // 4rem + 1px for border

const tc = createTableColumns<IndexAttemptError>();

const columns = [
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
  tc.column("document_id", {
    header: "Document ID",
    weight: 25,
    enableSorting: false,
    cell: (value, row) => {
      const label = value ?? row.entity_id ?? "Unknown";
      if (row.document_link) {
        return (
          <a
            href={row.document_link}
            target="_blank"
            rel="noopener noreferrer"
            className="text-link hover:underline"
          >
            <Text as="span" font="main-ui-body" color="text-04">
              {label}
            </Text>
          </a>
        );
      }
      return (
        <Text as="span" font="main-ui-body" color="text-04">
          {label}
        </Text>
      );
    },
  }),
  tc.column("failure_message", {
    header: "Error Message",
    weight: 42,
    enableSorting: false,
    cell: (value) => (
      <Text as="span" font="main-ui-body" color="text-04">
        {value}
      </Text>
    ),
  }),
  tc.column("is_resolved", {
    header: "Status",
    weight: 15,
    enableSorting: false,
    cell: (value) => (
      <span
        className={`px-2 py-1 rounded text-xs ${
          value
            ? "bg-status-success-02 text-status-success-05"
            : "bg-status-error-02 text-status-error-05"
        }`}
      >
        {value ? "Resolved" : "Unresolved"}
      </span>
    ),
  }),
];

export interface IndexAttemptErrorsModalProps {
  errors: {
    items: IndexAttemptError[];
  };
  totalPages: number;
  currentPage: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  onClose: () => void;
  onResolveAll: () => void;
  isResolvingErrors?: boolean;
}

export default function IndexAttemptErrorsModal({
  errors,
  totalPages,
  currentPage,
  onPageChange,
  onPageSizeChange,
  onClose,
  onResolveAll,
  isResolvingErrors = false,
}: IndexAttemptErrorsModalProps) {
  const observerRef = useRef<ResizeObserver | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const tableContainerRef = useCallback(
    (container: HTMLDivElement | null) => {
      if (observerRef.current) {
        observerRef.current.disconnect();
        observerRef.current = null;
      }
      if (!container) return;

      const observer = new ResizeObserver(() => {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(() => {
          const thead = container.querySelector("thead");
          const theadHeight = thead?.getBoundingClientRect().height ?? 0;
          const availableHeight = container.clientHeight - theadHeight;
          const newPageSize = Math.max(
            3,
            Math.floor(availableHeight / ROW_HEIGHT)
          );
          onPageSizeChange(newPageSize);
        }, 150);
      });

      observer.observe(container);
      observerRef.current = observer;
    },
    [onPageSizeChange]
  );

  const hasUnresolvedErrors = useMemo(
    () => errors.items.some((error) => !error.is_resolved),
    [errors.items]
  );

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="full" height="full">
        <Modal.Header
          icon={SvgAlertTriangle}
          title="Indexing Errors"
          description={
            isResolvingErrors
              ? "Currently attempting to resolve all errors by performing a full re-index. This may take some time to complete."
              : undefined
          }
          onClose={onClose}
          height="fit"
        />
        <Modal.Body height="full">
          {!isResolvingErrors && (
            <Section flexDirection="column" height="fit" gap={0.5}>
              <Text as="p" font="main-ui-body" color="text-03">
                Below are the errors encountered during indexing. Each row
                represents a failed document or entity.
              </Text>
              <Text as="p" font="main-ui-body" color="text-03">
                Click the button below to kick off a full re-index to try and
                resolve these errors. This full re-index may take much longer
                than a normal update.
              </Text>
            </Section>
          )}

          <Section ref={tableContainerRef} alignItems="stretch" height="full">
            <Table
              data={errors.items}
              columns={columns}
              getRowId={(row) => String(row.id)}
            />
          </Section>

          {totalPages > 1 && (
            <Section flexDirection="row" height="fit">
              <Pagination
                variant="list"
                currentPage={currentPage}
                totalPages={totalPages}
                onChange={onPageChange}
              />
            </Section>
          )}
        </Modal.Body>
        <Modal.Footer>
          {hasUnresolvedErrors && !isResolvingErrors && (
            // TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved
            <Button onClick={onResolveAll} className="ml-4 whitespace-nowrap">
              Resolve All
            </Button>
          )}
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
