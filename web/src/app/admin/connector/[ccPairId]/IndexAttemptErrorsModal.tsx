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
import { useTranslations } from "next-intl";
export interface IndexAttemptErrorsModalProps {
  errors: {
    items: IndexAttemptError[];
    total_items: number;
  };
  onClose: () => void;
  onResolveAll: () => void;
  isResolvingErrors?: boolean;
}

const ROW_HEIGHT = 65; // 4rem + 1px for border

export default function IndexAttemptErrorsModal({
  errors,
  onClose,
  onResolveAll,
  isResolvingErrors = false,
}: IndexAttemptErrorsModalProps) {
  const t = useTranslations("admin.connectors");
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

  // When data changes, reset to page 1.
  // When page size changes (resize), preserve the user's position by
  // finding which new page contains the first item they were looking at.
  const prevPageSizeRef = useRef(pageSize);
  useEffect(() => {
    if (pageSize !== prevPageSizeRef.current) {
      setCurrentPage((prev) => {
        const firstVisibleIndex = (prev - 1) * prevPageSizeRef.current;
        const newPage = Math.floor(firstVisibleIndex / pageSize) + 1;
        const totalPages = Math.ceil(errors.items.length / pageSize);
        return Math.min(newPage, totalPages);
      });
      prevPageSizeRef.current = pageSize;
    } else {
      setCurrentPage(1);
    }
  }, [errors.items.length, pageSize]);

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
      <Modal.Content width="full" height="full">
        <Modal.Header
          icon={SvgAlertTriangle}
          title={t("indexingErrors")}
          description={
            isResolvingErrors
              ? t("resolvingAllErrors")
              : undefined
          }
          onClose={onClose}
          height="fit"
        />
        <Modal.Body height="full">
          {!isResolvingErrors && (
            <div className="flex flex-col gap-2 flex-shrink-0">
              <Text as="p">
                {t("indexingErrorsDescription")}
              </Text>
              <Text as="p">
                {t("indexingErrorsResolveDescription")}
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
                  <TableHead>{t("time")}</TableHead>
                  <TableHead>{t("documentId")}</TableHead>
                  <TableHead className="w-1/2">{t("errorMessage")}</TableHead>
                  <TableHead>{t("status")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {paginationData.currentPageItems.length > 0 ? (
                  paginationData.currentPageItems.map((error) => (
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
                            {error.document_id || error.entity_id || t("unknown")}
                          </a>
                        ) : (
                          error.document_id || error.entity_id || t("unknown")
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
                              ? "bg-green-100 text-green-800"
                              : "bg-red-100 text-red-800"
                          }`}
                        >
                          {error.is_resolved ? t("resolved") : t("unresolved")}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow className="h-[4rem]">
                    <TableCell
                      colSpan={4}
                      className="text-center py-8 text-gray-500"
                    >
                      {t("noErrorsOnPage")}
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
              {t("resolveAll")}
            </Button>
          )}
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
