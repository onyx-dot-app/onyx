"use client";

import {
  Table,
  TableHead,
  TableRow,
  TableHeaderCell,
  TableBody,
  TableCell,
  Text,
  Button,
  Divider,
} from "@tremor/react";
import { IndexAttemptStatus } from "@/components/Status";
import { CCPairFullInfo } from "./types";
import { useState } from "react";
import { PageSelector } from "@/components/PageSelector";
import { localizeAndPrettify } from "@/lib/time";
import { getDocsProcessedPerMinute } from "@/lib/indexAttempt";
import { Modal } from "@/components/Modal";
import { CheckmarkIcon, CopyIcon, SearchIcon } from "@/components/icons/icons";
import Link from "next/link";
import ExceptionTraceModal from "@/components/modals/ExceptionTraceModal";

const NUM_IN_PAGE = 8;

export function IndexingAttemptsTable({ ccPair }: { ccPair: CCPairFullInfo }) {
  const [page, setPage] = useState(1);
  const [indexAttemptTracePopupId, setIndexAttemptTracePopupId] = useState<
    number | null
  >(null);
  const indexAttemptToDisplayTraceFor = ccPair.index_attempts.find(
    (indexAttempt) => indexAttempt.id === indexAttemptTracePopupId
  );
  const [copyClicked, setCopyClicked] = useState(false);

  return (
    <>
      {indexAttemptToDisplayTraceFor &&
        indexAttemptToDisplayTraceFor.full_exception_trace && (
          <ExceptionTraceModal
            onOutsideClick={() => setIndexAttemptTracePopupId(null)}
            exceptionTrace={indexAttemptToDisplayTraceFor.full_exception_trace!}
          />
        )}

      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Time Started</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell>New Doc Cnt</TableHeaderCell>
            <TableHeaderCell>Total Doc Cnt</TableHeaderCell>
            <TableHeaderCell>Error Message</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {ccPair.index_attempts
            .slice(NUM_IN_PAGE * (page - 1), NUM_IN_PAGE * page)
            .map((indexAttempt) => {
              const docsPerMinute =
                getDocsProcessedPerMinute(indexAttempt)?.toFixed(2);
              return (
                <TableRow key={indexAttempt.id}>
                  <TableCell>
                    {indexAttempt.time_started
                      ? localizeAndPrettify(indexAttempt.time_started)
                      : "-"}
                  </TableCell>
                  <TableCell>
                    <IndexAttemptStatus
                      status={indexAttempt.status || "not_started"}
                      size="xs"
                    />
                    {docsPerMinute && (
                      <div className="text-xs mt-1">
                        {docsPerMinute} docs / min
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex">
                      <div className="text-right">
                        <div>{indexAttempt.new_docs_indexed}</div>
                        {indexAttempt.docs_removed_from_index > 0 && (
                          <div className="text-xs w-52 text-wrap flex italic overflow-hidden whitespace-normal px-1">
                            (also removed {indexAttempt.docs_removed_from_index}{" "}
                            docs that were detected as deleted in the source)
                          </div>
                        )}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>{indexAttempt.total_docs_indexed}</TableCell>
                  <TableCell>
                    <div>
                      {indexAttempt.error_count > 0 && (
                        <Link
                          className="cursor-pointer my-auto"
                          href={`/admin/indexing/${indexAttempt.id}`}
                        >
                          <Text className="flex flex-wrap text-link whitespace-normal">
                            <SearchIcon />
                            &nbsp;View Errors
                          </Text>
                        </Link>
                      )}

                      {indexAttempt.status === "success" && (
                        <Text className="flex flex-wrap whitespace-normal">
                          {"-"}
                        </Text>
                      )}

                      {indexAttempt.status === "failed" &&
                        indexAttempt.error_msg && (
                          <Text className="flex flex-wrap whitespace-normal">
                            {indexAttempt.error_msg}
                          </Text>
                        )}

                      {indexAttempt.full_exception_trace && (
                        <div
                          onClick={() => {
                            setIndexAttemptTracePopupId(indexAttempt.id);
                          }}
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
      {ccPair.index_attempts.length > NUM_IN_PAGE && (
        <div className="mt-3 flex">
          <div className="mx-auto">
            <PageSelector
              totalPages={Math.ceil(ccPair.index_attempts.length / NUM_IN_PAGE)}
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
