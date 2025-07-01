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

interface IndexAttemptErrorsModalProps {
  errors: {
    items: IndexAttemptError[];
    total_items: number;
  };
  onClose: () => void;
  onResolveAll: () => void;
  isResolvingErrors?: boolean;
  onPageChange: (page: number) => void;
  currentPage: number;
  pageSize?: number;
}

const DEFAULT_PAGE_SIZE = 10;

export default function IndexAttemptErrorsModal({
  errors,
  onClose,
  onResolveAll,
  isResolvingErrors = false,
  onPageChange,
  currentPage,
  pageSize = DEFAULT_PAGE_SIZE,
}: IndexAttemptErrorsModalProps) {
  // // Add fake errors for testing
  // const fakeErrors: IndexAttemptError[] = [
  //   {
  //     id: 1,
  //     time_created: new Date(Date.now() - 1000 * 60 * 30).toISOString(), // 30 minutes ago
  //     document_id: "doc-123",
  //     document_link: "https://example.com/doc-123",
  //     failure_message: "Failed to parse PDF: Invalid file format",
  //     is_resolved: false,
  //     entity_id: null,
  //     connector_credential_pair_id: 1,
  //     failed_time_range_start: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
  //     failed_time_range_end: new Date(Date.now()).toISOString(),
  //     index_attempt_id: 1,
  //   },
  //   {
  //     id: 2,
  //     time_created: new Date(Date.now() - 1000 * 60 * 60 * 2).toISOString(), // 2 hours ago
  //     document_id: "doc-456",
  //     document_link: null,
  //     failure_message: "Network timeout while fetching document content",
  //     is_resolved: true,
  //     entity_id: null,
  //     connector_credential_pair_id: 1,
  //     failed_time_range_start: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
  //     failed_time_range_end: new Date(Date.now()).toISOString(),
  //     index_attempt_id: 1,
  //   },
  //   {
  //     id: 3,
  //     time_created: new Date(Date.now() - 1000 * 60 * 60 * 24).toISOString(), // 1 day ago
  //     document_id: null,
  //     document_link: null,
  //     failure_message: "Entity extraction failed: Missing required fields",
  //     is_resolved: false,
  //     entity_id: "entity-789",
  //     connector_credential_pair_id: 1,
  //     failed_time_range_start: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
  //     failed_time_range_end: new Date(Date.now()).toISOString(),
  //     index_attempt_id: 1,
  //   },
  //   {
  //     id: 4,
  //     time_created: new Date(Date.now() - 1000 * 60 * 60 * 24 * 3).toISOString(), // 3 days ago
  //     document_id: "doc-999",
  //     document_link: "https://example.com/doc-999",
  //     failure_message: "Authentication failed: Invalid credentials",
  //     is_resolved: false,
  //     entity_id: null,
  //     connector_credential_pair_id: 1,
  //     failed_time_range_start: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
  //     failed_time_range_end: new Date(Date.now()).toISOString(),
  //     index_attempt_id: 1,
  //   },
  //   {
  //     id: 5,
  //     time_created: new Date(Date.now() - 1000 * 60 * 60 * 24 * 7).toISOString(), // 1 week ago
  //     document_id: "doc-888",
  //     document_link: null,
  //     failure_message: "File size exceeds maximum allowed limit (100MB)",
  //     is_resolved: true,
  //     entity_id: null,
  //     connector_credential_pair_id: 1,
  //     failed_time_range_start: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
  //     failed_time_range_end: new Date(Date.now()).toISOString(),
  //     index_attempt_id: 1,
  //   },
  // ];

  // // Override the errors with fake data for testing
  // errors.items = [...fakeErrors, ...errors.items];
  // errors.total_items += fakeErrors.length;

  const totalPages = Math.ceil(errors.total_items / pageSize);
  const hasUnresolvedErrors = errors.items.some((error) => !error.is_resolved);
  return (
    <Modal title="Indexing Errors" onOutsideClick={onClose} width="max-w-6xl">
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
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

        <div>
          <div className="bg-neutral-50 dark:bg-neutral-800 border-b sticky top-0 z-10">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>Document ID</TableHead>
                  <TableHead className="w-1/2">Error Message</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
            </Table>
          </div>
          {/* Scrollable body */}
          <div className="max-h-[50vh] overflow-y-auto overflow-x-auto">
            <Table>
              <TableBody>
                {errors.items.map((error) => (
                  <TableRow key={error.id}>
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
                    <TableCell className="whitespace-normal">
                      {error.failure_message}
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
                ))}
              </TableBody>
            </Table>
          </div>
        </div>

        <div className="mt-4">
          {totalPages > 1 && (
            <div className="flex-1 flex justify-center mb-2">
              <PageSelector
                totalPages={totalPages}
                currentPage={currentPage}
                onPageChange={(page) => onPageChange(page)}
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
