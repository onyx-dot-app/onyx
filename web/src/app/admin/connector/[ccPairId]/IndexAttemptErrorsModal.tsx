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
import { useState } from "react";
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
            {errors.items.map((error) => (
              <TableRow key={error.id}>
                <TableCell>{localizeAndPrettify(error.time_created)}</TableCell>
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

        <div className="mt-4">
          {totalPages > 1 && (
            <div className="flex-1 flex justify-center mb-2">
              <PageSelector
                totalPages={totalPages}
                currentPage={currentPage + 1}
                onPageChange={(page) => onPageChange(page - 1)}
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
