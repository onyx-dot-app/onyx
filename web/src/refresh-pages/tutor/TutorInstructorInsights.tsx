"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { Button } from "@opal/components";
import { SvgBarChart, SvgEye, SvgRefreshCw, SvgThumbsDown } from "@opal/icons";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ThreeDotsLoader } from "@/components/Loading";
import { ErrorCallout } from "@/components/ErrorCallout";
import Text from "@/refresh-components/texts/Text";
import InputDatePicker from "@/refresh-components/inputs/InputDatePicker";
import Modal from "@/refresh-components/Modal";
import { PageSelector } from "@/components/PageSelector";
import { Feedback } from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import usePaginatedFetch from "@/hooks/usePaginatedFetch";
import {
  ChatSessionMinimal,
  ChatSessionSnapshot,
} from "@/app/ee/admin/performance/usage/types";
import {
  QueryHistoryTableRow,
  SelectFeedbackType,
} from "@/app/ee/admin/performance/query-history/QueryHistoryTable";
import { QueryHistorySessionDetail } from "@/app/ee/admin/performance/query-history/QueryHistorySessionDetail";

const ITEMS_PER_PAGE = 12;
const PAGES_PER_BATCH = 2;

interface LtiInstructorDailyTrend {
  date: string;
  session_count: number;
  message_count: number;
}

interface LtiInstructorThemeCluster {
  label: string;
  summary: string;
  count: number;
  friction_score: number;
  representative_question: string | null;
}

interface LtiInstructorTrendsResponse {
  start: string;
  end: string;
  total_sessions: number;
  total_messages: number;
  daily: LtiInstructorDailyTrend[];
  feedback_count: number;
  thumbs_down_count: number;
  thumbs_down_rate: number;
  themes: LtiInstructorThemeCluster[] | null;
  summary: string | null;
}

function startOfDay(date: Date) {
  const next = new Date(date);
  next.setHours(0, 0, 0, 0);
  return next;
}

function endOfDay(date: Date) {
  const next = new Date(date);
  next.setHours(23, 59, 59, 999);
  return next;
}

function defaultStartDate() {
  const date = new Date();
  date.setDate(date.getDate() - 6);
  return startOfDay(date);
}

function formatDay(dateStr: string) {
  const [year, month, day] = dateStr.split("-").map(Number);
  if (year === undefined || month === undefined || day === undefined) {
    return dateStr;
  }
  return new Date(year, month - 1, day).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

function StatBlock({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="rounded-md border border-border bg-background p-3">
      <Text as="p" className="text-xs text-subtle">
        {label}
      </Text>
      <Text as="p" className="mt-1 text-2xl font-semibold">
        {value}
      </Text>
    </div>
  );
}

function VolumeChart({ daily }: { daily: LtiInstructorDailyTrend[] }) {
  const maxCount = Math.max(
    1,
    ...daily.map((point) => Math.max(point.session_count, point.message_count))
  );

  return (
    <div className="rounded-md border border-border bg-background p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <SvgBarChart size={18} />
          <Text as="p" className="font-medium">
            Volume
          </Text>
        </div>
        <div className="flex items-center gap-3 text-xs text-subtle">
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-emerald-500" />
            Sessions
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-sky-500" />
            Messages
          </span>
        </div>
      </div>
      <div className="flex h-44 items-end gap-3 overflow-x-auto border-b border-border pb-2">
        {daily.map((point) => (
          <div
            key={point.date}
            className="flex h-full min-w-12 flex-1 flex-col items-center justify-end gap-2"
          >
            <div className="flex h-32 w-full items-end justify-center gap-1">
              <div
                className="w-3 rounded-t bg-emerald-500"
                style={{
                  height:
                    point.session_count === 0
                      ? 0
                      : `${Math.max(
                          4,
                          (point.session_count / maxCount) * 100
                        )}%`,
                }}
                title={`${point.session_count} sessions`}
              />
              <div
                className="w-3 rounded-t bg-sky-500"
                style={{
                  height:
                    point.message_count === 0
                      ? 0
                      : `${Math.max(
                          4,
                          (point.message_count / maxCount) * 100
                        )}%`,
                }}
                title={`${point.message_count} messages`}
              />
            </div>
            <span className="text-xs text-subtle">{formatDay(point.date)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ThemeCards({
  themes,
  summary,
}: {
  themes: LtiInstructorThemeCluster[] | null;
  summary: string | null;
}) {
  if (!themes || themes.length === 0) {
    return (
      <div className="rounded-md border border-border bg-background p-4">
        <Text as="p" className="font-medium">
          Topics
        </Text>
        <Text as="p" className="mt-2 text-sm text-subtle">
          No themes available for this window.
        </Text>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {summary && (
        <div className="rounded-md border border-border bg-background p-4">
          <Text as="p" className="font-medium">
            Summary
          </Text>
          <Text as="p" className="mt-2 text-sm">
            {summary}
          </Text>
        </div>
      )}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {themes.map((theme) => (
          <div
            key={`${theme.label}-${theme.count}-${theme.friction_score}`}
            className="rounded-md border border-border bg-background p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <Text as="p" className="font-medium">
                {theme.label}
              </Text>
              <span className="shrink-0 rounded bg-background-tint-02 px-2 py-1 text-xs">
                {theme.count}
              </span>
            </div>
            <Text as="p" className="mt-2 text-sm text-subtle">
              {theme.summary}
            </Text>
            <div className="mt-3 flex items-center gap-2 text-xs text-subtle">
              <SvgThumbsDown size={14} />
              Friction {theme.friction_score}
            </div>
            {theme.representative_question && (
              <Text as="p" className="mt-3 line-clamp-3 text-sm">
                {theme.representative_question}
              </Text>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function TutorInstructorInsights({
  projectId,
}: {
  projectId: number;
}) {
  const [startDate, setStartDate] = useState(defaultStartDate);
  const [endDate, setEndDate] = useState(() => endOfDay(new Date()));
  const [feedbackType, setFeedbackType] = useState<Feedback | "all">("all");
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(
    null
  );

  const handleStartDateChange = (date: Date | null) => {
    if (!date) return;
    const nextStart = startOfDay(date);
    setStartDate(nextStart);
    if (nextStart > endDate) {
      setEndDate(endOfDay(nextStart));
    }
  };

  const handleEndDateChange = (date: Date | null) => {
    if (!date) return;
    const nextEnd = endOfDay(date);
    setEndDate(nextEnd);
    if (nextEnd < startDate) {
      setStartDate(startOfDay(nextEnd));
    }
  };

  const filters = useMemo(() => {
    const nextFilters: Record<string, string | number> = {
      project_id: projectId,
      start_time: startDate.toISOString(),
      end_time: endDate.toISOString(),
    };
    if (feedbackType !== "all") {
      nextFilters.feedback_type = feedbackType;
    }
    return nextFilters;
  }, [projectId, startDate, endDate, feedbackType]);

  const trendParams = useMemo(() => {
    const params = new URLSearchParams();
    params.set("project_id", String(projectId));
    params.set("start", startDate.toISOString());
    params.set("end", endDate.toISOString());
    params.set("include_themes", "true");
    return params.toString();
  }, [projectId, startDate, endDate]);

  const {
    data: trends,
    isLoading: trendsLoading,
    error: trendsError,
    mutate: refreshTrends,
  } = useSWR<LtiInstructorTrendsResponse>(
    `/api/lti/instructor/trends?${trendParams}`,
    errorHandlingFetcher,
    { refreshInterval: 60_000 }
  );

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
    endpoint: "/api/lti/instructor/query-history",
    filter: filters,
    refreshIntervalInMs: 30_000,
  });

  const detailKey = selectedSessionId
    ? `/api/lti/instructor/query-history/${selectedSessionId}?project_id=${projectId}`
    : null;
  const { data: selectedSession, isLoading: detailLoading } =
    useSWR<ChatSessionSnapshot>(detailKey, errorHandlingFetcher);

  if (error) {
    return (
      <ErrorCallout
        errorTitle="Error fetching query history"
        errorMsg={error.message}
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-y-auto bg-background-tint-01">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-5 p-4 md:p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <Text as="p" className="text-xs font-medium text-subtle">
                Start
              </Text>
              <InputDatePicker
                selectedDate={startDate}
                setSelectedDate={handleStartDateChange}
                maxDate={new Date()}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Text as="p" className="text-xs font-medium text-subtle">
                End
              </Text>
              <InputDatePicker
                selectedDate={endDate}
                setSelectedDate={handleEndDateChange}
                maxDate={new Date()}
              />
            </div>
            <SelectFeedbackType
              value={feedbackType}
              onValueChange={setFeedbackType}
            />
          </div>
          <Button
            prominence="secondary"
            icon={SvgRefreshCw}
            onClick={() => void refreshTrends()}
          >
            Refresh
          </Button>
        </div>

        {trendsError && (
          <ErrorCallout
            errorTitle="Error fetching trends"
            errorMsg={trendsError.message}
          />
        )}

        {trendsLoading || !trends ? (
          <div className="flex h-48 items-center justify-center">
            <ThreeDotsLoader />
          </div>
        ) : (
          <>
            <div className="grid gap-3 md:grid-cols-4">
              <StatBlock label="Sessions" value={trends.total_sessions} />
              <StatBlock label="Messages" value={trends.total_messages} />
              <StatBlock
                label="Thumbs-down rate"
                value={`${Math.round(trends.thumbs_down_rate * 100)}%`}
              />
              <StatBlock label="Feedback" value={trends.feedback_count} />
            </div>
            <VolumeChart daily={trends.daily} />
            <ThemeCards themes={trends.themes} summary={trends.summary} />
          </>
        )}

        <div className="rounded-md border border-border bg-background p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <Text as="p" className="font-medium">
              Query History
            </Text>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>First User Message</TableHead>
                <TableHead>First AI Response</TableHead>
                <TableHead>Feedback</TableHead>
                <TableHead>Persona</TableHead>
                <TableHead>Date</TableHead>
              </TableRow>
            </TableHeader>
            {isLoading ? (
              <TableBody>
                <TableRow>
                  <TableCell colSpan={5} className="text-center">
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
                    showUser={false}
                    onSelect={() => setSelectedSessionId(chatSessionMinimal.id)}
                  />
                ))}
                {chatSessionData?.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-subtle">
                      No sessions found.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            )}
          </Table>

          {chatSessionData && (
            <div className="mt-4">
              <PageSelector
                totalPages={totalPages}
                currentPage={currentPage}
                onPageChange={goToPage}
              />
            </div>
          )}
        </div>
      </div>

      <Modal
        open={selectedSessionId !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedSessionId(null);
        }}
      >
        <Modal.Content width="lg" height="full">
          <Modal.Header
            icon={SvgEye}
            title="Session Detail"
            onClose={() => setSelectedSessionId(null)}
          />
          <Modal.Body>
            {detailLoading || !selectedSession ? (
              <ThreeDotsLoader />
            ) : (
              <QueryHistorySessionDetail
                chatSessionSnapshot={selectedSession}
                title="Transcript"
              />
            )}
          </Modal.Body>
        </Modal.Content>
      </Modal>
    </div>
  );
}
