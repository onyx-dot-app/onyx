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
import { useCallback, useEffect, useRef, useState, useMemo } from "react";
import { SvgAlertTriangle } from "@opal/icons";
export interface IndexAttemptErrorsModalProps {
  errors: {
    items: IndexAttemptError[];
    total_items: number;
  };
  onClose: () => void;
  onResolveAll: () => void;
  isResolvingErrors?: boolean;
}

const ROW_HEIGHT = 60;

export default function IndexAttemptErrorsModal({
  errors,
  onClose,
  onResolveAll,
  isResolvingErrors = false,
}: IndexAttemptErrorsModalProps) {
  const observerRef = useRef<ResizeObserver | null>(null);
  const [pageSize, setPageSize] = useState(10);
  const [currentPage, setCurrentPage] = useState(1);

  const tableContainerRef = useCallback((container: HTMLDivElement | null) => {
    if (observerRef.current) {
      observerRef.current.disconnect();
      observerRef.current = null;
    }

    if (!container) return;

    const observer = new ResizeObserver(() => {
      const thead = container.querySelector("thead");
      const theadHeight = thead?.getBoundingClientRect().height ?? 0;
      const availableHeight = container.clientHeight - theadHeight;
      const newPageSize = Math.max(3, Math.floor(availableHeight / ROW_HEIGHT));
      setPageSize(newPageSize);
    });

    observer.observe(container);
    observerRef.current = observer;
  }, []);

  // Reset to page 1 when data or page size changes
  useEffect(() => {
    setCurrentPage(1);
  }, [errors.items.length, errors.total_items, pageSize]);

  const paginationData = useMemo(() => {
    const totalPages = Math.ceil(errors.items.length / pageSize);
    const startIndex = (currentPage - 1) * pageSize;
    const currentPageItems = errors.items.slice(
      startIndex,
      startIndex + pageSize
    );
    return { totalPages, currentPageItems };
  }, [errors.items, pageSize, currentPage]);

  const hasUnresolvedErrors = useMemo(
    () => errors.items.some((error) => !error.is_resolved),
    [errors.items]
  );

  const handlePageChange = (page: number) => {
    // Ensure we don't go to an invalid page
    if (page >= 1 && page <= paginationData.totalPages) {
      setCurrentPage(page);
    }
  };

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="lg" height="full">
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
                {paginationData.currentPageItems.length > 0 ? (
                  paginationData.currentPageItems.map((error) => (
                    <TableRow key={error.id} className="h-[60px]">
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
                        <div className="overflow-y-auto whitespace-normal">
                          {error.failure_message}
                        </div>
                      </TableCell>
                      <TableCell>
                        <span
                          className={`px-2 py-1 rounded text-xs ${
                            error.is_resolved
                              ? "bg-green-100 text-green-800"
                              : "bg-red-100 text-red-800"
                          }`}
                        >
                          {error.is_resolved ? "Resolved" : "Unresolved"}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow className="h-[60px]">
                    <TableCell
                      colSpan={4}
                      className="text-center py-8 text-gray-500"
                    >
                      No errors found on this page
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>

          {paginationData.totalPages > 1 && (
            <div className="flex w-full justify-center">
              <PageSelector
                totalPages={paginationData.totalPages}
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
