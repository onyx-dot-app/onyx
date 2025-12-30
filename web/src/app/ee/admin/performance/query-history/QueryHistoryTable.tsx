import Separator from "@/refresh-components/Separator";
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
import { ThreeDotsLoader } from "@/components/Loading";
import { ChatSessionMinimal } from "@/app/ee/admin/performance/usage/types";
import { timestampToReadableDate } from "@/lib/dateUtils";
import { Dispatch, SetStateAction, useCallback, useState } from "react";
import { Feedback, TaskStatus } from "@/lib/types";
import {
  DateRange,
  AdminDateRangeSelector,
} from "@/components/dateRangeSelectors/AdminDateRangeSelector";
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
  PREVIOUS_CSV_TASK_BUTTON_NAME,
} from "@/app/ee/admin/performance/query-history/constants";
import { humanReadableFormatWithTime } from "@/lib/time";
import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
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
  return (
    <TableRow
      key={chatSessionMinimal.id}
      className="hover:bg-accent-background cursor-pointer relative select-none"
    >
      <TableCell>
        <Text as="p" className="whitespace-normal line-clamp-5">
          {chatSessionMinimal.first_user_message ||
            chatSessionMinimal.name ||
            "-"}
        </Text>
      </TableCell>
      <TableCell>
        <Text as="p" className="whitespace-normal line-clamp-5">
          {chatSessionMinimal.first_ai_message || "-"}
        </Text>
      </TableCell>
      <TableCell>
        <FeedbackBadge feedback={chatSessionMinimal.feedback_type} />
      </TableCell>
      <TableCell>{chatSessionMinimal.user_email || "-"}</TableCell>
      <TableCell>{chatSessionMinimal.assistant_name || "Unknown"}</TableCell>
      <TableCell>
        {timestampToReadableDate(chatSessionMinimal.time_created)}
      </TableCell>
      {/* Wrapping in <td> to avoid console warnings */}
      <td className="w-0 p-0">
        <Link
          href={
            `/ee/admin/performance/query-history/${chatSessionMinimal.id}` as Route
          }
          className="absolute w-full h-full left-0"
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
  return (
    <div>
      <Text as="p" className="my-auto mr-2 font-medium mb-1">
        Feedback Type
      </Text>
      <div className="max-w-sm space-y-6">
        <InputSelect
          value={value}
          onValueChange={onValueChange as (value: string) => void}
        >
          <InputSelect.Trigger />

          <InputSelect.Content>
            <InputSelect.Item value="all" icon={SvgMinusCircle}>
              Any
            </InputSelect.Item>
            <InputSelect.Item value="like" icon={SvgThumbsUp}>
              Like
            </InputSelect.Item>
            <InputSelect.Item value="dislike" icon={SvgThumbsDown}>
              Dislike
            </InputSelect.Item>
            <InputSelect.Item value="mixed" icon={SvgMinus}>
              Mixed
            </InputSelect.Item>
          </InputSelect.Content>
        </InputSelect>
      </div>
    </div>
  );
}

function ExportBadge({ status }: { status: TaskStatus }) {
  if (status === "SUCCESS") return <Badge variant="success">Success</Badge>;
  else if (status === "FAILURE")
    return <Badge variant="destructive">Failure</Badge>;
  else if (status === "PENDING" || status === "STARTED")
    return <Badge variant="in_progress">Pending</Badge>;
  else return <></>;
}

function PreviousQueryHistoryExportsModal({
  setShowModal,
}: {
  setShowModal: Dispatch<SetStateAction<boolean>>;
}) {
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
      <Modal.Content large>
        <Modal.Header
          icon={SvgFileText}
          title="Previous Query History Exports"
          onClose={() => setShowModal(false)}
        />
        <Modal.Body>
          <div className="flex flex-col w-full">
            <div className="flex flex-1">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Generated At</TableHead>
                    <TableHead>Start Range</TableHead>
                    <TableHead>End Range</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Download</TableHead>
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
                        {task.status === "SUCCESS" ? (
                          <a
                            className="flex justify-center"
                            href={withRequestId(
                              DOWNLOAD_QUERY_HISTORY_URL,
                              task.taskId
                            )}
                          >
                            <SvgDownloadCloud className="h-4 w-4 text-action-link-05" />
                          </a>
                        ) : (
                          <SvgDownloadCloud className="h-4 w-4 text-action-link-05 opacity-20" />
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            <div className="flex mt-3">
              <div className="mx-auto">
                <PageSelector
                  currentPage={taskPage}
                  totalPages={totalTaskPages}
                  onPageChange={setTaskPage}
                />
              </div>
            </div>
          </div>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}

export function QueryHistoryTable() {
  const [dateRange, setDateRange] = useState<DateRange>(undefined);
  const [filters, setFilters] = useState<{
    feedback_type?: Feedback | "all";
    start_time?: string;
    end_time?: string;
  }>({});

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

  const onTimeRangeChange = useCallback((value: DateRange) => {
    setDateRange(value);

    if (value?.from && value?.to) {
      setFilters((prev) => ({
        ...prev,
        start_time: value.from.toISOString(),
        end_time: value.to.toISOString(),
      }));
    } else {
      setFilters((prev) => {
        const newFilters = { ...prev };
        delete newFilters.start_time;
        delete newFilters.end_time;
        return newFilters;
      });
    }
  }, []);

  if (error) {
    return (
      <ErrorCallout
        errorTitle="Error fetching query history"
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

            <AdminDateRangeSelector
              value={dateRange}
              onValueChange={onTimeRangeChange}
            />
          </div>
          <div className="flex flex-row w-full items-center gap-x-2">
            <KickoffCSVExport dateRange={dateRange} />
            <Button secondary onClick={() => setShowModal(true)}>
              {PREVIOUS_CSV_TASK_BUTTON_NAME}
            </Button>
          </div>
        </div>
        <Separator />
        <Table className="mt-5">
          <TableHeader>
            <TableRow>
              <TableHead>First User Message</TableHead>
              <TableHead>First AI Response</TableHead>
              <TableHead>Feedback</TableHead>
              <TableHead>User</TableHead>
              <TableHead>Persona</TableHead>
              <TableHead>Date</TableHead>
            </TableRow>
          </TableHeader>
          {isLoading ? (
            <TableBody>
              <TableRow>
                <TableCell colSpan={6} className="text-center">
                  <ThreeDotsLoader />
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
          <div className="mt-3 flex">
            <div className="mx-auto">
              <PageSelector
                totalPages={totalPages}
                currentPage={currentPage}
                onPageChange={goToPage}
              />
            </div>
          </div>
        )}
      </CardSection>

      {showModal && (
        <PreviousQueryHistoryExportsModal setShowModal={setShowModal} />
      )}
    </>
  );
}
