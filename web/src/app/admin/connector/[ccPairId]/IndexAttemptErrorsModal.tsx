import { Modal } from "@/components/Modal";
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
import { Button } from "@/components/ui/button";
import { PageSelector } from "@/components/PageSelector";
import { useEffect, useState, useMemo } from "react";

interface IndexAttemptErrorsModalProps {
  errors: {
    items: IndexAttemptError[];
    total_items: number;
  };
  onClose: () => void;
  onResolveAll: () => void;
  isResolvingErrors?: boolean;
  onPageChange?: (page: number) => void;
  currentPage?: number;
  pageSize?: number;
}

export default function IndexAttemptErrorsModal({
  errors,
  onClose,
  onResolveAll,
  isResolvingErrors = false,
  pageSize: propPageSize,
}: IndexAttemptErrorsModalProps) {
  const [calculatedPageSize, setCalculatedPageSize] = useState(10);
  const [currentPage, setCurrentPage] = useState(1);

  // Reset to page 1 when the error list actually changes
  useEffect(() => {
    setCurrentPage(1);
  }, [errors.items.length, errors.total_items]);

  useEffect(() => {
    const calculatePageSize = () => {
      // Modal height is 75% of viewport height
      const modalHeight = window.innerHeight * 0.6;

      // Estimate heights (in pixels):
      // - Modal header (title + description): ~120px
      // - Table header: ~40px
      // - Pagination section: ~80px
      // - Modal padding: ~64px (32px top + 32px bottom)
      const fixedHeight = 120 + 40 + 80 + 64;

      // Available height for table rows
      const availableHeight = modalHeight - fixedHeight;

      // Each table row is approximately 60px (including borders and padding)
      const rowHeight = 60;

      // Calculate how many rows can fit, with a minimum of 3
      const rowsPerPage = Math.max(3, Math.floor(availableHeight / rowHeight));

      setCalculatedPageSize((prev) => {
        // Only update if the new size is significantly different to prevent flickering
        if (Math.abs(prev - rowsPerPage) > 0) {
          return rowsPerPage;
        }
        return prev;
      });
    };

    // Initial calculation
    calculatePageSize();

    // Debounced resize handler to prevent excessive recalculation
    let resizeTimeout: NodeJS.Timeout;
    const debouncedCalculatePageSize = () => {
      clearTimeout(resizeTimeout);
      resizeTimeout = setTimeout(calculatePageSize, 100);
    };

    window.addEventListener("resize", debouncedCalculatePageSize);
    return () => {
      window.removeEventListener("resize", debouncedCalculatePageSize);
      clearTimeout(resizeTimeout);
    };
  }, []);

  // Separate effect to reset current page when page size changes
  useEffect(() => {
    setCurrentPage(1);
  }, [calculatedPageSize]);

  const pageSize = propPageSize || calculatedPageSize;

  // Memoize pagination calculations to prevent unnecessary recalculations
  const paginationData = useMemo(() => {
    const totalPages = Math.ceil(errors.items.length / pageSize);
    const startIndex = (currentPage - 1) * pageSize;
    const endIndex = startIndex + pageSize;
    const currentPageItems = errors.items.slice(startIndex, endIndex);

    return {
      totalPages,
      currentPageItems,
      startIndex,
      endIndex,
    };
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
    <Modal
      title="Indexing Errors"
      onOutsideClick={onClose}
      width="max-w-6xl"
      heightOverride="[60vh]"
      hideOverflow={true}
    >
      <div className="flex flex-col gap-4 h-full">
        <div className="flex flex-col gap-2 flex-shrink-0">
          {isResolvingErrors ? (
            <div className="text-sm text-text-default">
              Currently attempting to resolve all errors by performing a full
              re-index. This may take some time to complete.
            </div>
          ) : (
            <>
              <div className="text-sm text-text-default">
                Below are the errors encountered during indexing. Each row
                represents a failed document or entity.
              </div>
              <div className="text-sm text-text-default">
                Click the button below to kick off a full re-index to try and
                resolve these errors. This full re-index may take much longer
                than a normal update.
              </div>
            </>
          )}
        </div>

        <div className="flex-1 overflow-hidden min-h-0">
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
                  <TableRow key={error.id} className="h-[60px] max-h-[60px]">
                    <TableCell className="h-[60px] align-top">
                      {localizeAndPrettify(error.time_created)}
                    </TableCell>
                    <TableCell className="h-[60px] align-top">
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
                    <TableCell className="h-[60px] align-top p-0">
                      <div className="h-[60px] overflow-y-auto p-4 whitespace-normal">
                        {error.failure_message}
                      </div>
                    </TableCell>
                    <TableCell className="h-[60px] align-top">
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
                <TableRow>
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

        <div className="flex-shrink-0">
          {paginationData.totalPages > 1 && (
            <div className="flex-1 flex justify-center mb-2">
              <PageSelector
                totalPages={paginationData.totalPages}
                currentPage={currentPage}
                onPageChange={handlePageChange}
              />
            </div>
          )}

          <div className="flex w-full">
            <div className="flex gap-2 ml-auto">
              {hasUnresolvedErrors && !isResolvingErrors && (
                <Button
                  onClick={onResolveAll}
                  variant="default"
                  className="ml-4 whitespace-nowrap"
                >
                  Resolve All
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>
    </Modal>
  );
}
