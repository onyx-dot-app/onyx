"use client";

import { type ReactNode, useMemo, useState } from "react";
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
import { errorHandlingFetcher } from "@/lib/fetcher";
import usePaginatedFetch from "@/hooks/usePaginatedFetch";
import TutorTabHeader from "@/refresh-pages/tutor/TutorTabHeader";
import {
  ChatSessionMinimal,
  ChatSessionSnapshot,
} from "@/app/ee/admin/performance/usage/types";
import { QueryHistoryTableRow } from "@/app/ee/admin/performance/query-history/QueryHistoryTable";
import { QueryHistorySessionDetail } from "@/app/ee/admin/performance/query-history/QueryHistorySessionDetail";

const ITEMS_PER_PAGE = 12;
const PAGES_PER_BATCH = 2;

interface LtiInstructorDailyTrend {
  date: string;
  session_count: number;
  message_count: number;
  positive_feedback_count: number;
  negative_feedback_count: number;
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

function ChartTooltip({ children }: { children: ReactNode }) {
  return (
    <div className="pointer-events-none absolute left-1/2 top-1 z-20 hidden min-w-max -translate-x-1/2 rounded bg-neutral-950 px-2 py-1 text-xs font-medium text-white shadow-lg group-hover:block">
      {children}
    </div>
  );
}

function VolumeChart({ trends }: { trends: LtiInstructorTrendsResponse }) {
  const daily = trends.daily;
  const positiveFeedbackCount = Math.max(
    0,
    trends.feedback_count - trends.thumbs_down_count
  );
  const thumbsDownRate =
    trends.feedback_count === 0
      ? ""
      : `, ${Math.round(trends.thumbs_down_rate * 100)}%`;
  const maxCount = Math.max(
    1,
    ...daily.map((point) =>
      Math.max(
        point.session_count,
        point.message_count,
        point.positive_feedback_count + point.negative_feedback_count
      )
    )
  );
  const getBarHeight = (count: number) =>
    count === 0 ? 0 : `${Math.max(4, (count / maxCount) * 100)}%`;
  const yAxisTicks =
    maxCount === 1 ? [maxCount, 0] : [maxCount, Math.ceil(maxCount / 2), 0];

  return (
    <div className="rounded-md border border-border bg-background p-4">
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex items-center gap-2">
          <SvgBarChart size={18} />
          <Text as="p" className="font-medium">
            Volume
          </Text>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-2 text-xs text-subtle">
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-indigo-500" />
            Sessions ({trends.total_sessions})
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-sky-500" />
            Messages ({trends.total_messages})
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-emerald-500" />
            Positive feedback ({positiveFeedbackCount})
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-rose-500" />
            Negative feedback ({`${trends.thumbs_down_count}${thumbsDownRate}`})
          </span>
        </div>
      </div>
      <div className="grid grid-cols-[2rem_minmax(0,1fr)] gap-x-3">
        <div className="flex h-36 flex-col justify-between text-right text-xs text-subtle">
          {yAxisTicks.map((tick) => (
            <span key={tick}>{tick}</span>
          ))}
        </div>
        <div className="relative overflow-x-auto border-b border-border pb-2">
          <div className="pointer-events-none absolute left-0 right-0 top-0 flex h-36 flex-col justify-between">
            {yAxisTicks.map((tick) => (
              <span key={tick} className="border-t border-border" />
            ))}
          </div>
          <div className="relative flex h-52 min-w-full items-end gap-3">
            {daily.map((point) => {
              const feedbackCount =
                point.positive_feedback_count + point.negative_feedback_count;
              const positiveFeedbackHeight =
                feedbackCount === 0
                  ? 0
                  : `${(point.positive_feedback_count / feedbackCount) * 100}%`;
              const negativeFeedbackHeight =
                feedbackCount === 0
                  ? 0
                  : `${(point.negative_feedback_count / feedbackCount) * 100}%`;

              return (
                <div
                  key={point.date}
                  className="flex h-full min-w-16 flex-1 flex-col items-center justify-end gap-2"
                >
                  <div className="flex h-36 w-full items-end justify-center gap-1.5">
                    <div className="group relative flex h-full w-4 items-end justify-center">
                      <ChartTooltip>
                        {point.session_count} sessions
                      </ChartTooltip>
                      <div
                        className="w-3 rounded-t bg-indigo-500"
                        style={{ height: getBarHeight(point.session_count) }}
                      />
                    </div>
                    <div className="group relative flex h-full w-4 items-end justify-center">
                      <ChartTooltip>
                        {point.message_count} messages
                      </ChartTooltip>
                      <div
                        className="w-3 rounded-t bg-sky-500"
                        style={{ height: getBarHeight(point.message_count) }}
                      />
                    </div>
                    <div className="group relative flex h-full w-4 items-end justify-center">
                      <ChartTooltip>
                        <span>{feedbackCount} feedback</span>
                        <span className="block">
                          {point.positive_feedback_count} positive
                        </span>
                        <span className="block">
                          {point.negative_feedback_count} negative
                        </span>
                      </ChartTooltip>
                      <div
                        className="flex w-3 flex-col justify-end overflow-hidden rounded-t"
                        style={{ height: getBarHeight(feedbackCount) }}
                      >
                        {point.negative_feedback_count > 0 && (
                          <div
                            className="w-full bg-rose-500"
                            style={{ height: negativeFeedbackHeight }}
                          />
                        )}
                        {point.positive_feedback_count > 0 && (
                          <div
                            className="w-full bg-emerald-500"
                            style={{ height: positiveFeedbackHeight }}
                          />
                        )}
                      </div>
                    </div>
                  </div>
                  <span className="text-xs text-subtle">
                    {formatDay(point.date)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
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
    return nextFilters;
  }, [projectId, startDate, endDate]);

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

  return (
    <div className="flex h-full min-h-0 w-full flex-col bg-background-tint-01">
      <TutorTabHeader
        icon={SvgBarChart}
        title="Insights"
        description="Tutor activity and student friction"
        rightChildren={
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
            <Button
              prominence="secondary"
              icon={SvgRefreshCw}
              onClick={() => void refreshTrends()}
            >
              Refresh
            </Button>
          </div>
        }
      />

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-7xl flex-col gap-5 p-4 md:p-6">
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
              <VolumeChart trends={trends} />
              <ThemeCards themes={trends.themes} summary={trends.summary} />
            </>
          )}

          {error ? (
            <ErrorCallout
              errorTitle="Error fetching query history"
              errorMsg={error.message}
            />
          ) : (
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
                        onSelect={() =>
                          setSelectedSessionId(chatSessionMinimal.id)
                        }
                      />
                    ))}
                    {chatSessionData?.length === 0 && (
                      <TableRow>
                        <TableCell
                          colSpan={5}
                          className="text-center text-subtle"
                        >
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
