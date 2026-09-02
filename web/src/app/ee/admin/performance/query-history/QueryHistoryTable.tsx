"use client";

import { useTranslations } from "next-intl";
import {
  Table,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
  TableHeader,
} from "@/components/ui/table";
import Text from "@/refresh-components/texts/Text";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import SvgSimpleLoader from "@opal/icons/simple-loader";
import { ChatSessionMinimal } from "@/app/ee/admin/performance/usage/types";
import { Section } from "@/layouts/general-layouts";
import { timestampToReadableDate } from "@/lib/dateUtils";
import { Dispatch, SetStateAction, useState } from "react";
import { Feedback, TaskStatus } from "@/lib/types";
import { DateRange } from "@/refresh-components/DateRangePicker";
import { PageSelector } from "@/components/PageSelector";
import Link from "next/link";
import type { Route } from "next";
import { FeedbackBadge } from "@/app/ee/admin/performance/query-history/FeedbackBadge";
import KickoffCSVExport from "@/app/ee/admin/performance/query-history/KickoffCSVExport";
import CardSection from "@/components/admin/CardSection";
import usePaginatedFetch from "@/hooks/usePaginatedFetch";
import { ErrorCallout } from "@/components/ErrorCallout";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR from "swr";
import { TaskQueueState } from "@/app/ee/admin/performance/query-history/types";
import { withRequestId } from "@/app/ee/admin/performance/query-history/utils";
import {
  DOWNLOAD_QUERY_HISTORY_URL,
  LIST_QUERY_HISTORY_URL,
  NUM_IN_PAGE,
  ITEMS_PER_PAGE,
  PAGES_PER_BATCH,
} from "@/app/ee/admin/performance/query-history/constants";
import { humanReadableFormatWithTime } from "@opal/time";
import { Modal } from "@opal/components";
import { Button, Divider } from "@opal/components";
import { Badge } from "@/components/ui/badge";
import {
  SvgDownloadCloud,
  SvgFileText,
  SvgMinus,
  SvgMinusCircle,
  SvgThumbsDown,
  SvgThumbsUp,
} from "@opal/icons";

function QueryHistoryTableRow({
  chatSessionMinimal,
}: {
  chatSessionMinimal: ChatSessionMinimal;
}) {
  const t = useTranslations("admin.queryHistory");
  return (
    <TableRow
      key={chatSessionMinimal.id}
      className="hover:bg-accent-background cursor-pointer relative select-none"
    >
      <TableCell className="max-w-xs">
        <Text className="whitespace-normal line-clamp-5">
          {chatSessionMinimal.first_user_message ||
            chatSessionMinimal.name ||
            "-"}
        </Text>
      </TableCell>
      <TableCell>
        <Text className="whitespace-normal line-clamp-5">
          {chatSessionMinimal.first_ai_message || "-"}
        </Text>
      </TableCell>
      <TableCell>
        <FeedbackBadge feedback={chatSessionMinimal.feedback_type} />
      </TableCell>
      <TableCell>{chatSessionMinimal.user_email || "-"}</TableCell>
      <TableCell>
        {chatSessionMinimal.assistant_name || t("assistant.unknown.label")}
      </TableCell>
      <TableCell>
        {timestampToReadableDate(chatSessionMinimal.time_created)}
      </TableCell>
      {/* Wrapping in <td> to avoid console warnings */}
      <td className="w-0 p-0">
        <Link
          href={
            `/ee/admin/performance/query-history/${chatSessionMinimal.id}` as Route
          }
          className="absolute w-full h-full start-0 top-0"
        ></Link>
      </td>
    </TableRow>
  );
}

function SelectFeedbackType({
  value,
  onValueChange,
}: {
  value: Feedback | "all";
  onValueChange: (value: Feedback | "all") => void;
}) {
  const t = useTranslations("admin.queryHistory");
  return (
    <Section alignItems="start" gap={1}>
      <Text as="p" className="font-medium">
        {t("filters.feedbackType.label")}
      </Text>
      <InputSelect
        value={value}
        onValueChange={onValueChange as (value: string) => void}
      >
        <InputSelect.Trigger />

        <InputSelect.Content>
          <InputSelect.Item value="all" icon={SvgMinusCircle}>
            {t("filters.any.label")}
          </InputSelect.Item>
          <InputSelect.Item value="like" icon={SvgThumbsUp}>
            {t("feedback.like.label")}
          </InputSelect.Item>
          <InputSelect.Item value="dislike" icon={SvgThumbsDown}>
            {t("feedback.dislike.label")}
          </InputSelect.Item>
          <InputSelect.Item value="mixed" icon={SvgMinus}>
            {t("feedback.mixed.label")}
          </InputSelect.Item>
        </InputSelect.Content>
      </InputSelect>
    </Section>
  );
}

function ExportBadge({ status }: { status: TaskStatus }) {
  const t = useTranslations("admin.queryHistory");
  if (status === "SUCCESS")
    return <Badge variant="success">{t("exportStatus.success.label")}</Badge>;
  else if (status === "FAILURE")
    return (
      <Badge variant="destructive">{t("exportStatus.failure.label")}</Badge>
    );
  else if (status === "PENDING" || status === "STARTED")
    return (
      <Badge variant="in_progress">{t("exportStatus.pending.label")}</Badge>
    );
  else return <></>;
}

function PreviousQueryHistoryExportsModal({
  setShowModal,
}: {
  setShowModal: Dispatch<SetStateAction<boolean>>;
}) {
  const t = useTranslations("admin.queryHistory");
  const { data: queryHistoryTasks } = useSWR<TaskQueueState[]>(
    LIST_QUERY_HISTORY_URL,
    errorHandlingFetcher,
    {
      refreshInterval: 3000,
    }
  );

  const tasks = (queryHistoryTasks ?? []).map((queryHistory) => ({
    taskId: queryHistory.task_id,
    start: new Date(queryHistory.start),
    end: new Date(queryHistory.end),
    status: queryHistory.status,
    startTime: queryHistory.start_time,
  }));

  // sort based off of "most-recently-exported" CSV file.
  tasks.sort((task_a, task_b) => {
    if (task_a.startTime < task_b.startTime) return 1;
    else if (task_a.startTime > task_b.startTime) return -1;
    else return 0;
  });

  const [taskPage, setTaskPage] = useState(1);
  const totalTaskPages = Math.ceil(tasks.length / NUM_IN_PAGE);
  const paginatedTasks = tasks.slice(
    NUM_IN_PAGE * (taskPage - 1),
    NUM_IN_PAGE * taskPage
  );

  return (
    <Modal open onOpenChange={() => setShowModal(false)}>
      <Modal.Content width="full" height="full">
        <Modal.Header
          icon={SvgFileText}
          title={t("exportsModal.header.title")}
          onClose={() => setShowModal(false)}
        />
        <Modal.Body>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("exportsModal.generatedAt.header")}</TableHead>
                <TableHead>{t("exportsModal.startRange.header")}</TableHead>
                <TableHead>{t("exportsModal.endRange.header")}</TableHead>
                <TableHead>{t("exportsModal.status.header")}</TableHead>
                <TableHead>{t("exportsModal.download.header")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {paginatedTasks.map((task, index) => (
                <TableRow key={index}>
                  <TableCell>
                    {humanReadableFormatWithTime(task.startTime)}
                  </TableCell>
                  <TableCell>{task.start.toDateString()}</TableCell>
                  <TableCell>{task.end.toDateString()}</TableCell>
                  <TableCell>
                    <ExportBadge status={task.status} />
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="default"
                      prominence="tertiary"
                      icon={SvgDownloadCloud}
                      size="sm"
                      disabled={task.status !== "SUCCESS"}
                      tooltip={
                        task.status !== "SUCCESS"
                          ? t("exportsModal.notReady.tooltip")
                          : undefined
                      }
                      href={
                        task.status === "SUCCESS"
                          ? withRequestId(
                              DOWNLOAD_QUERY_HISTORY_URL,
                              task.taskId
                            )
                          : undefined
                      }
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          <Section>
            <PageSelector
              currentPage={taskPage}
              totalPages={totalTaskPages}
              onPageChange={setTaskPage}
            />
          </Section>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}

export type QueryHistoryFilters = Record<
  string,
  string | number | boolean | string[] | Date
> & {
  feedback_type?: Feedback | "all";
  start_time?: string;
  end_time?: string;
};

interface QueryHistoryTableProps {
  dateRange: DateRange;
  filters: QueryHistoryFilters;
  setFilters: Dispatch<SetStateAction<QueryHistoryFilters>>;
}

export function QueryHistoryTable({
  dateRange,
  filters,
  setFilters,
}: QueryHistoryTableProps) {
  const t = useTranslations("admin.queryHistory");
  const [showModal, setShowModal] = useState(false);

  const {
    currentPageData: chatSessionData,
    isLoading,
    error,
    currentPage,
    totalPages,
    goToPage,
  } = usePaginatedFetch<ChatSessionMinimal>({
    itemsPerPage: ITEMS_PER_PAGE,
    pagesPerBatch: PAGES_PER_BATCH,
    endpoint: "/api/admin/chat-session-history",
    filter: filters,
  });

  if (error) {
    return (
      <ErrorCallout
        errorTitle={t("table.fetchError.title")}
        errorMsg={error?.message}
      />
    );
  }

  return (
    <>
      <CardSection className="mt-8">
        <div className="flex">
          <div className="gap-y-3 flex flex-col">
            <SelectFeedbackType
              value={filters.feedback_type || "all"}
              onValueChange={(value) => {
                setFilters((prev) => {
                  const newFilters = { ...prev };
                  if (value === "all") {
                    delete newFilters.feedback_type;
                  } else {
                    newFilters.feedback_type = value;
                  }
                  return newFilters;
                });
              }}
            />
          </div>
          <div className="flex flex-row w-full items-center gap-x-2">
            <KickoffCSVExport dateRange={dateRange} />
            <Button prominence="secondary" onClick={() => setShowModal(true)}>
              {t("previousExports.label")}
            </Button>
          </div>
        </div>
        <Divider />
        <Section>
          <Table className="mt-5">
            <TableHeader>
              <TableRow>
                <TableHead>{t("table.firstUserMessage.header")}</TableHead>
                <TableHead>{t("table.firstAiResponse.header")}</TableHead>
                <TableHead>{t("table.feedback.header")}</TableHead>
                <TableHead>{t("table.user.header")}</TableHead>
                <TableHead>{t("table.persona.header")}</TableHead>
                <TableHead>{t("table.date.header")}</TableHead>
              </TableRow>
            </TableHeader>
            {isLoading ? (
              <TableBody>
                <TableRow>
                  <TableCell colSpan={6} className="text-center">
                    <div className="flex justify-center">
                      <SvgSimpleLoader className="h-6 w-6" />
                    </div>
                  </TableCell>
                </TableRow>
              </TableBody>
            ) : (
              <TableBody>
                {chatSessionData?.map((chatSessionMinimal) => (
                  <QueryHistoryTableRow
                    key={chatSessionMinimal.id}
                    chatSessionMinimal={chatSessionMinimal}
                  />
                ))}
              </TableBody>
            )}
          </Table>

          {chatSessionData && (
            <Section>
              <PageSelector
                totalPages={totalPages}
                currentPage={currentPage}
                onPageChange={goToPage}
              />
            </Section>
          )}
        </Section>
      </CardSection>

      {showModal && (
        <PreviousQueryHistoryExportsModal setShowModal={setShowModal} />
      )}
    </>
  );
}
