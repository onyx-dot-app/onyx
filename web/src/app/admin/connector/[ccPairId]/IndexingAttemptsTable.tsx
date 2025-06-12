"use client";

import { useState } from "react";
import {
  Table,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
  TableHeader,
} from "@/components/ui/table";
import Text from "@/components/ui/text";
import { Callout } from "@/components/ui/callout";
import { CCPairFullInfo } from "./types";
import { IndexAttemptSnapshot } from "@/lib/types";
import { IndexAttemptStatus } from "@/components/Status";
import { PageSelector } from "@/components/PageSelector";
import { localizeAndPrettify } from "@/lib/time";
import { getDocsProcessedPerMinute } from "@/lib/indexAttempt";
import { InfoIcon } from "@/components/icons/icons";
import ExceptionTraceModal from "@/components/modals/ExceptionTraceModal";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { FaBarsProgress } from "react-icons/fa6";

export interface IndexingAttemptsTableProps {
  ccPair: CCPairFullInfo;
  indexAttempts: IndexAttemptSnapshot[];
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

export function IndexingAttemptsTable({
  indexAttempts,
  currentPage,
  totalPages,
  onPageChange,
}: IndexingAttemptsTableProps) {
  const [indexAttemptTracePopupId, setIndexAttemptTracePopupId] = useState<
    number | null
  >(null);

  if (!indexAttempts?.length) {
    return (
      <Callout
        className="mt-4"
        title="No indexing attempts scheduled yet"
        type="notice"
      >
        Index attempts are scheduled in the background, and may take some time
        to appear. Try refreshing the page in ~30 seconds!
      </Callout>
    );
  }

  const indexAttemptToDisplayTraceFor = indexAttempts?.find(
    (indexAttempt) => indexAttempt.id === indexAttemptTracePopupId
  );

  return (
    <>
      {indexAttemptToDisplayTraceFor?.full_exception_trace && (
        <ExceptionTraceModal
          onOutsideClick={() => setIndexAttemptTracePopupId(null)}
          exceptionTrace={indexAttemptToDisplayTraceFor.full_exception_trace}
        />
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Time Started</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="whitespace-nowrap">New Docs</TableHead>
            <TableHead>
              <div className="w-fit whitespace-nowrap">
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="flex items-center">
                        Total Docs
                        <InfoIcon className="ml-1 w-4 h-4" />
                      </span>
                    </TooltipTrigger>
                    <TooltipContent>
                      Total number of documents replaced in the index during
                      this indexing attempt
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </TableHead>
            <TableHead>Error Message</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {indexAttempts.map((indexAttempt) => {
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
                  />
                  {docsPerMinute ? (
                    <div className="text-xs mt-1">
                      {docsPerMinute} docs / min
                    </div>
                  ) : (
                    indexAttempt.status === "success" && (
                      <div className="text-xs mt-1">
                        No additional docs processed
                      </div>
                    )
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
                <TableCell>
                  <div className="flex items-center">
                    {indexAttempt.total_docs_indexed}
                    {indexAttempt.from_beginning && (
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span className="cursor-help flex items-center">
                              <FaBarsProgress className="ml-2 h-3.5 w-3.5" />
                            </span>
                          </TooltipTrigger>
                          <TooltipContent>
                            This index attempt{" "}
                            {indexAttempt.status === "in_progress" ||
                            indexAttempt.status === "not_started"
                              ? "is"
                              : "was"}{" "}
                            a full re-index. All documents from the source{" "}
                            {indexAttempt.status === "in_progress" ||
                            indexAttempt.status === "not_started"
                              ? "are being "
                              : "were "}
                            synced into the system.
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    )}
                  </div>
                </TableCell>
                <TableCell>
                  <div>
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
      {totalPages > 1 && (
        <div className="mt-3 flex">
          <div className="mx-auto">
            <PageSelector
              totalPages={totalPages}
              currentPage={currentPage}
              onPageChange={onPageChange}
            />
          </div>
        </div>
      )}
    </>
  );
}
