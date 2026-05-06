import Modal from "@/refresh-components/Modal";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { IndexAttemptError } from "./types";
import { localizeAndPrettify } from "@/lib/time";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { PageSelector } from "@/components/PageSelector";
import { useCallback, useMemo, useRef } from "react";
import { SvgAlertTriangle } from "@opal/icons";

const ROW_HEIGHT = 65; // 4rem + 1px for border

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

  const handlePageChange = (page: number) => {
    if (page >= 1 && page <= totalPages) {
      onPageChange(page);
    }
  };

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
            <div className="flex flex-col gap-2 flex-shrink-0">
              <Text as="p">
                Below are the errors encountered during indexing. Each row
                represents a failed document or entity.
              </Text>
              <Text as="p">
                Click the button below to kick off a full re-index to try and
                resolve these errors. This full re-index may take much longer
                than a normal update.
              </Text>
            </div>
          )}

          <div
            ref={tableContainerRef}
            className="flex-1 w-full overflow-hidden min-h-0"
          >
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>Document ID</TableHead>
                  <TableHead className="w-1/2">Error Message</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {errors.items.length > 0 ? (
                  errors.items.map((error) => (
                    <TableRow key={error.id} className="h-[4rem]">
                      <TableCell>
                        {localizeAndPrettify(error.time_created)}
                      </TableCell>
                      <TableCell>
                        {error.document_link ? (
                          <a
                            href={error.document_link}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-link hover:underline"
                          >
                            {error.document_id || error.entity_id || "Unknown"}
                          </a>
                        ) : (
                          error.document_id || error.entity_id || "Unknown"
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center h-[2rem] overflow-y-auto whitespace-normal">
                          {error.failure_message}
                        </div>
                      </TableCell>
                      <TableCell>
                        <span
                          className={`px-2 py-1 rounded text-xs ${
                            error.is_resolved
                              ? "bg-status-success-02 text-status-success-05"
                              : "bg-status-error-02 text-status-error-05"
                          }`}
                        >
                          {error.is_resolved ? "Resolved" : "Unresolved"}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow className="h-[4rem]">
                    <TableCell
                      colSpan={4}
                      className="text-center py-8 text-text-03"
                    >
                      No errors found on this page
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>

          {totalPages > 1 && (
            <div className="flex w-full justify-center">
              <PageSelector
                totalPages={totalPages}
                currentPage={currentPage}
                onPageChange={handlePageChange}
              />
            </div>
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
