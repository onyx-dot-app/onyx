"use client";

import { Modal } from "@/components/Modal";
import { PageSelector } from "@/components/PageSelector";
import { CheckmarkIcon, CopyIcon } from "@/components/icons/icons";
import { localizeAndPrettify } from "@/lib/time";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
  Text,
} from "@tremor/react";
import { useState } from "react";
import { IndexAttemptError } from "./types";

const NUM_IN_PAGE = 8;

export function CustomModal({
  isVisible,
  onClose,
  title,
  content,
  showCopyButton = false,
}: {
  isVisible: boolean;
  onClose: () => void;
  title: string;
  content: string;
  showCopyButton?: boolean;
}) {
  const [copyClicked, setCopyClicked] = useState(false);

  if (!isVisible) return null;

  return (
    <Modal
      width="w-4/6"
      className="h-5/6 overflow-y-hidden flex flex-col"
      title={title}
      onOutsideClick={onClose}
    >
      <div className="overflow-y-auto mb-6">
        {showCopyButton && (
          <div className="mb-6">
            {!copyClicked ? (
              <div
                onClick={() => {
                  navigator.clipboard.writeText(content);
                  setCopyClicked(true);
                  setTimeout(() => setCopyClicked(false), 2000);
                }}
                className="flex w-fit cursor-pointer hover:bg-hover-light p-2 border-border border rounded"
              >
                Copy full content
                <CopyIcon className="ml-2 my-auto" />
              </div>
            ) : (
              <div className="flex w-fit hover:bg-hover-light p-2 border-border border rounded cursor-default">
                Copied to clipboard
                <CheckmarkIcon
                  className="my-auto ml-2 flex flex-shrink-0 text-success"
                  size={16}
                />
              </div>
            )}
          </div>
        )}
        <div className="whitespace-pre-wrap">{content}</div>
      </div>
    </Modal>
  );
}

export function IndexAttemptErrorsTable({
  indexAttemptErrors,
}: {
  indexAttemptErrors: IndexAttemptError[];
}) {
  const [page, setPage] = useState(1);
  const [modalData, setModalData] = useState<{
    id: number | null;
    title: string;
    content: string;
  } | null>(null);
  const closeModal = () => setModalData(null);

  return (
    <>
      {modalData && (
        <CustomModal
          isVisible={!!modalData}
          onClose={closeModal}
          title={modalData.title}
          content={modalData.content}
          showCopyButton
        />
      )}

      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Timestamp</TableHeaderCell>
            <TableHeaderCell>Batch Number</TableHeaderCell>
            <TableHeaderCell>Document Summaries</TableHeaderCell>
            <TableHeaderCell>Error Message</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {indexAttemptErrors
            .slice(NUM_IN_PAGE * (page - 1), NUM_IN_PAGE * page)
            .map((indexAttemptError) => {
              return (
                <TableRow key={indexAttemptError.id}>
                  <TableCell>
                    {indexAttemptError.time_created
                      ? localizeAndPrettify(indexAttemptError.time_created)
                      : "-"}
                  </TableCell>
                  <TableCell>{indexAttemptError.batch_number}</TableCell>
                  <TableCell>
                    {indexAttemptError.doc_summaries && (
                      <div
                        onClick={() =>
                          setModalData({
                            id: indexAttemptError.id,
                            title: "Document Summaries",
                            content: JSON.stringify(
                              indexAttemptError.doc_summaries,
                              null,
                              2
                            ),
                          })
                        }
                        className="mt-2 text-link cursor-pointer select-none"
                      >
                        View Document Summaries
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <div>
                      <Text className="flex flex-wrap whitespace-normal">
                        {indexAttemptError.error_msg || "-"}
                      </Text>
                      {indexAttemptError.traceback && (
                        <div
                          onClick={() =>
                            setModalData({
                              id: indexAttemptError.id,
                              title: "Exception Traceback",
                              content: indexAttemptError.traceback!,
                            })
                          }
                          className="mt-2 text-link cursor-pointer select-none"
                        >
                          View Full Trace
                        </div>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
        </TableBody>
      </Table>
      {indexAttemptErrors.length > NUM_IN_PAGE && (
        <div className="mt-3 flex">
          <div className="mx-auto">
            <PageSelector
              totalPages={Math.ceil(indexAttemptErrors.length / NUM_IN_PAGE)}
              currentPage={page}
              onPageChange={(newPage) => {
                setPage(newPage);
                window.scrollTo({
                  top: 0,
                  left: 0,
                  behavior: "smooth",
                });
              }}
            />
          </div>
        </div>
      )}
    </>
  );
}
