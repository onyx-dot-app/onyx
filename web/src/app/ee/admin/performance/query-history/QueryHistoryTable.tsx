import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
  TableHeader,
} from "@/components/ui/table";
import Text from "@/components/ui/text";

import { FiDownload } from "react-icons/fi";
import {
  Select,
  SelectItem,
  SelectValue,
  SelectTrigger,
  SelectContent,
} from "@/components/ui/select";
import { ThreeDotsLoader } from "@/components/Loading";
import { ChatSessionMinimal } from "../usage/types";
import { timestampToReadableDate } from "@/lib/dateUtils";
import { FiFrown, FiMinus, FiSmile, FiMeh } from "react-icons/fi";
import { useCallback, useState } from "react";
import { Feedback } from "@/lib/types";
import { DateRange, DateRangeSelector } from "../DateRangeSelector";
import { PageSelector } from "@/components/PageSelector";
import Link from "next/link";
import { FeedbackBadge } from "./FeedbackBadge";
import { DownloadAsCSV } from "./DownloadAsCSV";
import CardSection from "@/components/admin/CardSection";
import usePaginatedFetch from "@/hooks/usePaginatedFetch";
import { ErrorCallout } from "@/components/ErrorCallout";
import Title from "@/components/ui/title";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR from "swr";
import { TaskQueueState } from "./types";
import { withRequestId } from "./utils";
import {
  DOWNLOAD_QUERY_HISTORY_URL,
  LIST_QUERY_HISTORY_URL,
} from "./constants";
import { humanReadableFormatWithTime } from "@/lib/time";

const ITEMS_PER_PAGE = 20;
const PAGES_PER_BATCH = 2;

function QueryHistoryTableRow({
  chatSessionMinimal,
}: {
  chatSessionMinimal: ChatSessionMinimal;
}) {
  return (
    <TableRow
      key={chatSessionMinimal.id}
      className="hover:bg-accent-background cursor-pointer relative"
    >
      <TableCell>
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
      <TableCell>{chatSessionMinimal.assistant_name || "Unknown"}</TableCell>
      <TableCell>
        {timestampToReadableDate(chatSessionMinimal.time_created)}
      </TableCell>
      {/* Wrapping in <td> to avoid console warnings */}
      <td className="w-0 p-0">
        <Link
          href={`/admin/performance/query-history/${chatSessionMinimal.id}`}
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
      <Text className="my-auto mr-2 font-medium mb-1">Feedback Type</Text>
      <div className="max-w-sm space-y-6">
        <Select
          value={value}
          onValueChange={onValueChange as (value: string) => void}
        >
          <SelectTrigger>
            <SelectValue placeholder="Select feedback type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">
              <div className="flex items-center gap-2">
                <FiMinus className="h-4 w-4" />
                <span>Any</span>
              </div>
            </SelectItem>
            <SelectItem value="like">
              <div className="flex items-center gap-2">
                <FiSmile className="h-4 w-4" />
                <span>Like</span>
              </div>
            </SelectItem>
            <SelectItem value="dislike">
              <div className="flex items-center gap-2">
                <FiFrown className="h-4 w-4" />
                <span>Dislike</span>
              </div>
            </SelectItem>
            <SelectItem value="mixed">
              <div className="flex items-center gap-2">
                <FiMeh className="h-4 w-4" />
                <span>Mixed</span>
              </div>
            </SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

export function QueryHistoryTable() {
  const [dateRange, setDateRange] = useState<DateRange>(undefined);
  const [filters, setFilters] = useState<{
    feedback_type?: Feedback | "all";
    start_time?: string;
    end_time?: string;
  }>({});

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

  const { data: queryHistoryTasks } = useSWR<TaskQueueState[]>(
    LIST_QUERY_HISTORY_URL,
    errorHandlingFetcher
  );

  const tasks = (queryHistoryTasks ?? []).map((queryHistory) => ({
    taskId: queryHistory.task_id,
    start: new Date(queryHistory.start),
    end: new Date(queryHistory.end),
    status: queryHistory.status,
    start_time: queryHistory.start_time,
  }));

  // sort based off of "most-recently-exported" CSV file.
  tasks.sort((task_a, task_b) => {
    if (task_a.start_time < task_b.start_time) return 1;
    else if (task_a.start_time > task_b.start_time) return -1;
    else return 0;
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

            <DateRangeSelector
              value={dateRange}
              onValueChange={onTimeRangeChange}
            />
          </div>
          <DownloadAsCSV dateRange={dateRange} />
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

      <Separator />

      <Title className="mb-2 mt-6 mx-auto">
        Previous Query History Exports
      </Title>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Export ID</TableHead>
            <TableHead>Start Range</TableHead>
            <TableHead>End Range</TableHead>
            <TableHead>Generated At</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Download</TableHead>
          </TableRow>
        </TableHeader>

        <TableBody>
          {tasks.map((task, index) => (
            <TableRow key={index}>
              <TableCell>{task.taskId}</TableCell>
              <TableCell>{task.start.toDateString()}</TableCell>
              <TableCell>{task.end.toDateString()}</TableCell>
              <TableCell>
                {humanReadableFormatWithTime(task.start_time)}
              </TableCell>
              <TableCell>{task.status}</TableCell>
              <TableCell>
                {task.status === "SUCCESS" ? (
                  <Link
                    className="flex justify-center"
                    href={withRequestId(
                      DOWNLOAD_QUERY_HISTORY_URL,
                      task.taskId
                    )}
                  >
                    <FiDownload color="primary" />
                  </Link>
                ) : (
                  <FiDownload color="primary" className="opacity-20" />
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </>
  );
}
