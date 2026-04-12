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
import { Text } from "@opal/components";
import { Callout } from "@/components/ui/callout";
import { CCPairFullInfo } from "./types";
import { IndexAttemptSnapshot } from "@/lib/types";
import { IndexAttemptStatus } from "@/components/Status";
import { PageSelector } from "@/components/PageSelector";
import { localizeAndPrettify } from "@/lib/time";
import { getDocsProcessedPerMinute } from "@/lib/indexAttempt";
import { InfoIcon } from "@/components/icons/icons";
import ExceptionTraceModal from "@/sections/modals/PreviewModal/ExceptionTraceModal";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import { SvgClock } from "@opal/icons";
import { useTranslations } from "next-intl";
export interface IndexingAttemptsTableProps {
  ccPair: CCPairFullInfo;
  indexAttempts: IndexAttemptSnapshot[];
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

export function IndexAttemptsTable({
  indexAttempts,
  currentPage,
  totalPages,
  onPageChange,
}: IndexingAttemptsTableProps) {
  const [indexAttemptTracePopupId, setIndexAttemptTracePopupId] = useState<
    number | null
  >(null);
  const t = useTranslations("admin.connectors");

  if (!indexAttempts?.length) {
    return (
      <Callout
        className="mt-4"
        title={t("noIndexingAttempts")}
        type="notice"
      >
        {t("noIndexingAttemptsDescription")}
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
            <TableHead>{t("timeStarted")}</TableHead>
            <TableHead>{t("status")}</TableHead>
            <TableHead className="whitespace-nowrap">{t("newDocs")}</TableHead>
            <TableHead>
              <SimpleTooltip
                tooltip={t("totalDocsTooltip")}
                side="top"
              >
                <span className="flex items-center">
                  {t("totalDocs")}
                  <InfoIcon className="ml-1 w-4 h-4" />
                </span>
              </SimpleTooltip>
            </TableHead>
            <TableHead>{t("errorMessage")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {indexAttempts.map((indexAttempt) => {
            const docsPerMinute =
              getDocsProcessedPerMinute(indexAttempt)?.toFixed(2);
            const isReindexInProgress =
              indexAttempt.status === "in_progress" ||
              indexAttempt.status === "not_started";
            const reindexTooltip = t("reindexTooltip", {
              is: isReindexInProgress ? "is" : "was",
              being: isReindexInProgress ? "are being" : "were",
            });
            return (
              <TableRow
                key={indexAttempt.id}
                className={
                  indexAttempt.full_exception_trace
                    ? "hover:bg-accent-background cursor-pointer relative select-none"
                    : undefined
                }
              >
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
                      {t("docsPerMin", { count: docsPerMinute })}
                    </div>
                  ) : (
                    indexAttempt.status === "success" && (
                      <div className="text-xs mt-1">
                        {t("noAdditionalDocsProcessed")}
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
                          {t("alsoRemovedDocs", { count: indexAttempt.docs_removed_from_index })}
                        </div>
                      )}
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex items-center">
                    {indexAttempt.total_docs_indexed}
                    {indexAttempt.from_beginning && (
                      <SimpleTooltip side="top" tooltip={reindexTooltip}>
                        <span className="cursor-help flex items-center">
                          <SvgClock className="ml-2 h-3.5 w-3.5 stroke-current" />
                        </span>
                      </SimpleTooltip>
                    )}
                  </div>
                </TableCell>
                <TableCell>
                  {indexAttempt.status === "success" && <Text as="p">-</Text>}

                  {indexAttempt.status === "failed" &&
                    indexAttempt.error_msg && (
                      <Text as="p">{indexAttempt.error_msg}</Text>
                    )}
                </TableCell>
                <td className="w-0 p-0">
                  {indexAttempt.full_exception_trace && (
                    <button
                      type="button"
                      aria-label={t("viewFullTrace")}
                      onClick={() =>
                        setIndexAttemptTracePopupId(indexAttempt.id)
                      }
                      className="absolute w-full h-full left-0 top-0"
                    />
                  )}
                </td>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      {totalPages > 1 && (
        <div className="flex flex-1 justify-center pt-3">
          <PageSelector
            totalPages={totalPages}
            currentPage={currentPage}
            onPageChange={onPageChange}
          />
        </div>
      )}
    </>
  );
}
