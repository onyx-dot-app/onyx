"use client";

import { IconLoader } from "@opal/loaders";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { startOfDay, subDays } from "date-fns";
import useSWR, { useSWRConfig } from "swr";
import {
  Button,
  Calendar,
  Dropdown,
  MessageCard,
  Pagination,
  Text,
  type DropdownMenuItem,
  type DropdownView,
} from "@opal/components";
import { ContentAction, Section, toast } from "@opal/layouts";
import { PageLoader } from "@opal/loaders";
import {
  SvgCalendar,
  SvgChevronLeft,
  SvgDownload,
  SvgDownloadCloud,
  SvgSpreadsheetFile,
  SvgX,
} from "@opal/icons";
import { humanReadableFormat, humanReadableFormatWithTime } from "@opal/time";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { UsageReport } from "@/app/ee/admin/performance/usage/types";
import {
  ReportPeriod,
  UsageReportJob,
} from "@/views/admin/WorkspaceAnalyticsPage/types";
import {
  generateUsageReport,
  usageReportDownloadUrl,
} from "@/views/admin/WorkspaceAnalyticsPage/svc";

function presetPeriod(days: number): ReportPeriod {
  const to = startOfDay(new Date());
  return { range: { from: subDays(to, days - 1), to } };
}

const PAGE_SIZE = 8;
const POLL_INTERVAL_MS = 3_000;

function isOpen(job: UsageReportJob): boolean {
  return job.status === "PENDING" || job.status === "STARTED";
}

function periodLabel(
  report: UsageReport,
  allTimeLabel: string,
  locale: string
): string {
  return report.period_from
    ? `${humanReadableFormat(report.period_from, locale)} – ${humanReadableFormat(
        report.period_to!,
        locale
      )}`
    : allTimeLabel;
}

function PendingReportRow() {
  const t = useTranslations("admin.analytics");
  return (
    <div
      className="rounded-12 border border-border-01 bg-background-tint-01"
      data-testid="pending-report-row"
    >
      <ContentAction
        font="main-ui-action"
        icon={SvgSpreadsheetFile}
        title={t("reports.pendingRow.title")}
        description={t("reports.pendingRow.slowDescription")}
        padding={1}
        center
        rightChildren={
          <IconLoader
            size={16}
            className="shrink-0 animate-spin stroke-text-03 motion-reduce:animate-none"
          />
        }
      />
    </div>
  );
}

interface ReportRowProps {
  report: UsageReport;
  justArrived: boolean;
}

function ReportRow({ report, justArrived }: ReportRowProps) {
  const t = useTranslations("admin.analytics");
  const locale = useLocale();
  const label = periodLabel(report, t("reports.period.allTime.label"), locale);
  return (
    <div
      className={
        justArrived
          ? "rounded-12 border border-border-01 bg-background-neutral-00 motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-top-2 motion-safe:duration-500"
          : "rounded-12 border border-border-01 bg-background-neutral-00"
      }
    >
      <ContentAction
        font="main-ui-action"
        icon={SvgSpreadsheetFile}
        title={label}
        description={t("reports.row.description", {
          requestor: report.requestor ?? t("reports.row.systemRequestor.label"),
          time: humanReadableFormatWithTime(report.time_created, locale),
        })}
        padding={1}
        center
        rightChildren={
          <Button
            prominence="tertiary"
            icon={SvgDownload}
            tooltip={t("reports.row.downloadButton.tooltip")}
            aria-label={t("reports.row.downloadButton.ariaLabel", { label })}
            href={usageReportDownloadUrl(report.report_name)}
          />
        }
      />
    </div>
  );
}

interface GenerateReportMenuProps {
  disabled: boolean;
  pending: boolean;
  onGenerate: (period: ReportPeriod) => void;
}

function GenerateReportMenu({
  disabled,
  pending,
  onGenerate,
}: GenerateReportMenuProps) {
  const t = useTranslations("admin.analytics");
  const [open, setOpen] = useState(false);
  const calendarRef = useRef<HTMLDivElement>(null);
  const [pendingStart, setPendingStart] = useState<Date | undefined>(undefined);
  const [draftRange, setDraftRange] = useState<
    { from: Date; to?: Date } | undefined
  >(undefined);

  const allTimeLabel = t("reports.period.allTime.label");
  const presetDays: { label: string; days: number }[] = [
    { label: t("reports.period.today.label"), days: 1 },
    { label: t("reports.period.last7Days.label"), days: 7 },
    { label: t("reports.period.last30Days.label"), days: 30 },
    { label: t("reports.period.last3Months.label"), days: 90 },
  ];

  function reset() {
    setPendingStart(undefined);
    setDraftRange(undefined);
  }

  // The custom page: a way back, then the calendar as one row of its own.
  const calendarView: DropdownView = {
    items: [
      {
        kind: "action",
        id: "back",
        icon: SvgChevronLeft,
        title: t("reports.period.custom.label"),
        onSelect: (views) => {
          reset();
          views.pop();
        },
      },
      {
        kind: "custom",
        id: "calendar",
        keepOpen: true,
        // ArrowRight steps into the calendar; its days take the keyboard
        // from there.
        onSecondary: () =>
          calendarRef.current?.querySelector("button")?.focus(),
        render: ({ props }) => (
          <div
            {...props}
            role="menuitem"
            tabIndex={-1}
            ref={calendarRef}
            // Escape from a focused day closes the list.
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setOpen(false);
                reset();
              }
            }}
          >
            <Section
              flexDirection="column"
              justifyContent="start"
              alignItems="stretch"
              gap={0.25}
              padding={0.5}
              width="full"
              height="fit"
            >
              <Text font="secondary-body" color="text-03">
                {pendingStart
                  ? t("reports.calendar.pickEnd.label")
                  : t("reports.calendar.pickStart.label")}
              </Text>
              <Calendar
                mode="range"
                selected={draftRange}
                onDayClick={(day) => {
                  if (!pendingStart) {
                    setDraftRange({ from: day });
                    setPendingStart(day);
                    return;
                  }
                  const from = day < pendingStart ? day : pendingStart;
                  const to = day < pendingStart ? pendingStart : day;
                  onGenerate({ range: { from, to } });
                  setOpen(false);
                  reset();
                }}
                numberOfMonths={1}
                disabled={(date) => date > new Date()}
              />
            </Section>
          </div>
        ),
      },
    ],
  };
  const items: DropdownMenuItem[] = [
    ...presetDays.map(
      (preset): DropdownMenuItem => ({
        kind: "action",
        id: `preset-${preset.days}`,
        title: preset.label,
        onSelect: () => onGenerate(presetPeriod(preset.days)),
      })
    ),
    {
      kind: "action",
      id: "all-time",
      title: allTimeLabel,
      onSelect: () => onGenerate({}),
    },
    {
      kind: "group",
      items: [
        {
          kind: "action",
          id: "custom",
          icon: SvgCalendar,
          title: t("reports.period.custom.label"),
          onSelect: (views) => views.push("calendar"),
        },
      ],
    },
  ];

  return (
    <Dropdown
      width={80}
      align="end"
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen) reset();
      }}
    >
      <Dropdown.Trigger asChild>
        <Button icon={SvgDownloadCloud} disabled={disabled}>
          {pending
            ? t("reports.generateButton.pendingLabel")
            : t("reports.generateButton.label")}
        </Button>
      </Dropdown.Trigger>
      <Dropdown.Data
        label={t("reports.generateButton.label")}
        items={items}
        views={{ calendar: calendarView }}
      />
    </Dropdown>
  );
}

export default function UsageReports() {
  const locale = useLocale();
  const t = useTranslations("admin.analytics");
  const [page, setPage] = useState(1);
  const [requesting, setRequesting] = useState(false);
  const [requestedReportId, setRequestedReportId] = useState<string | null>(
    null
  );
  const [arrivedReportName, setArrivedReportName] = useState<string | null>(
    null
  );
  const abortRef = useRef<AbortController | null>(null);

  const { mutate: mutateKey } = useSWRConfig();
  // A worker records the report in the transaction that deletes its job, so
  // reports read after a jobs response include every job that response lacks.
  // Read reports again after the first jobs read of a visit and when an open
  // job ends. A forced read also drops any older reports read in flight.
  const visitReadJobsRef = useRef(false);
  const openJobIdsRef = useRef<Set<string>>(new Set());
  const {
    data: jobs,
    error: jobsError,
    isLoading: jobsLoading,
    mutate: mutateJobs,
  } = useSWR<UsageReportJob[]>(SWR_KEYS.usageReportJobs, errorHandlingFetcher, {
    // The mount effect reads jobs, so cached jobs never replace a fresh read.
    revalidateOnMount: false,
    refreshInterval: (latest) => (latest?.some(isOpen) ? POLL_INTERVAL_MS : 0),
    onSuccess: (latest) => {
      const open = new Set(latest.filter(isOpen).map((job) => job.report_id));
      const ended = [...openJobIdsRef.current].some((id) => !open.has(id));
      openJobIdsRef.current = open;
      if (visitReadJobsRef.current && !ended) return;
      visitReadJobsRef.current = true;
      void mutateKey(SWR_KEYS.usageReport).catch((error: unknown) => {
        console.error("Failed to refresh the usage report list:", error);
      });
    },
  });
  useEffect(() => {
    void mutateJobs();
    return () => {
      // A back navigation can show this page again with its state kept.
      visitReadJobsRef.current = false;
    };
  }, [mutateJobs]);
  // Only the admin's own request blocks Generate. Jobs of other admins, or
  // from before a reload, show as rows but do not block a new request.
  const pending = (jobs ?? []).some(
    (job) => job.report_id === requestedReportId && isOpen(job)
  );
  const {
    data: reports,
    error: listError,
    mutate,
  } = useSWR<UsageReport[]>(SWR_KEYS.usageReport, errorHandlingFetcher, {
    // Reports load only after a jobs read, from the jobs onSuccess above.
    revalidateOnMount: false,
  });
  const listLoading = !reports && !listError;

  useEffect(() => {
    if (listError) console.error("Failed to load usage reports:", listError);
  }, [listError]);

  useEffect(() => {
    if (!requestedReportId) return;
    const completed = reports?.find((report) =>
      report.report_name.includes(requestedReportId)
    );
    if (completed) {
      setRequestedReportId(null);
      setArrivedReportName(completed.report_name);
      setPage(1);
      toast.success(t("reports.toasts.ready"));
    } else if (
      jobs?.some(
        (job) => job.report_id === requestedReportId && job.status === "FAILURE"
      )
    ) {
      setRequestedReportId(null);
      toast.error(t("reports.failedRow.title"));
    }
  }, [reports, jobs, requestedReportId, t]);

  useEffect(() => () => abortRef.current?.abort(), []);

  async function requestReport(period: ReportPeriod): Promise<void> {
    setRequesting(true);
    const abort = new AbortController();
    abortRef.current = abort;
    try {
      const reportId = await generateUsageReport(period, abort.signal);
      setRequestedReportId(reportId);
      setArrivedReportName(null);
      // Generation already started, so a failed refresh must not surface as
      // "failed to start report generation". Keep the button disabled until
      // the job list shows the new job. Read reports after jobs, as above.
      try {
        await mutateJobs();
        await mutate();
      } catch (error) {
        console.error("Failed to refresh the usage report list:", error);
      }
    } catch (error) {
      if (abort.signal.aborted) return;
      console.error("Failed to start usage report generation:", error);
      const message =
        error instanceof Error
          ? error.message
          : t("reports.toasts.unknownError");
      toast.error(t("reports.toasts.startFailed", { message }));
      return;
    } finally {
      if (!abort.signal.aborted) setRequesting(false);
    }
  }

  const orderedReports = useMemo(
    () =>
      [...(reports ?? [])].sort(
        (left, right) =>
          new Date(right.time_created).getTime() -
          new Date(left.time_created).getTime()
      ),
    [reports]
  );
  const totalPages = Math.max(1, Math.ceil(orderedReports.length / PAGE_SIZE));
  const pageReports = orderedReports.slice(
    PAGE_SIZE * (page - 1),
    PAGE_SIZE * page
  );

  return (
    <Section
      flexDirection="column"
      justifyContent="start"
      alignItems="stretch"
      gap={1}
      width="full"
      height="fit"
    >
      {/* sm:flex-row / sm:items-center / sm:justify-between have no Section equivalent, kept as a raw div */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <Section
          flexDirection="column"
          justifyContent="start"
          alignItems="stretch"
          gap={0.125}
          width="full"
          height="fit"
        >
          <Text font="heading-section">{t("reports.title")}</Text>
          <Text font="secondary-body" color="text-03">
            {t("reports.description")}
          </Text>
        </Section>
        <GenerateReportMenu
          disabled={requesting || pending}
          pending={pending}
          onGenerate={(period) => void requestReport(period)}
        />
      </div>

      {listError || jobsError ? (
        <MessageCard
          variant="error"
          icon={SvgX}
          title={t("reports.listError.title")}
        />
      ) : listLoading || jobsLoading ? (
        <PageLoader />
      ) : (
        <Section
          flexDirection="column"
          justifyContent="start"
          alignItems="stretch"
          gap={0.5}
          width="full"
          height="fit"
        >
          {page === 1 &&
            (jobs ?? []).map((job) =>
              job.status === "FAILURE" ? (
                <MessageCard
                  key={job.report_id}
                  variant="error"
                  icon={SvgX}
                  title={t("reports.failedRow.title")}
                  description={t("reports.failedRow.description", {
                    time: humanReadableFormatWithTime(job.time_created, locale),
                  })}
                />
              ) : isOpen(job) ? (
                <PendingReportRow key={job.report_id} />
              ) : null
            )}
          {orderedReports.length === 0 && !jobs?.length ? (
            <div className="rounded-12 border border-dashed border-border-02 p-4">
              <Text font="secondary-body" color="text-03" as="p">
                {t("reports.empty.description")}
              </Text>
            </div>
          ) : (
            pageReports.map((report) => (
              <ReportRow
                key={report.report_name}
                report={report}
                justArrived={report.report_name === arrivedReportName}
              />
            ))
          )}
          {totalPages > 1 && (
            <div className="flex justify-end pt-1">
              <Pagination
                variant="simple"
                currentPage={page}
                totalPages={totalPages}
                onChange={setPage}
              />
            </div>
          )}
        </Section>
      )}
    </Section>
  );
}
