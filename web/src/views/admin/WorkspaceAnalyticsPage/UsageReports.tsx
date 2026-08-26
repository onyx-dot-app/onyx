"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { format, startOfDay, subDays } from "date-fns";
import useSWR from "swr";
import {
  Button,
  Calendar,
  LineItemButton,
  MessageCard,
  Pagination,
  Popover,
  Text,
} from "@opal/components";
import { ContentAction, PageLoader, Section, toast } from "@opal/layouts";
import {
  SvgCalendar,
  SvgDownload,
  SvgDownloadCloud,
  SvgSimpleLoader,
  SvgSpreadsheetFile,
  SvgX,
} from "@opal/icons";
import { humanReadableFormat, humanReadableFormatWithTime } from "@opal/time";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { UsageReport } from "@/app/ee/admin/performance/usage/types";
import {
  PendingReport,
  ReportPeriod,
} from "@/views/admin/WorkspaceAnalyticsPage/interfaces";
import {
  generateUsageReport,
  usageReportDownloadUrl,
} from "@/views/admin/WorkspaceAnalyticsPage/svc";

function presetPeriod(label: string, days: number): ReportPeriod {
  const to = startOfDay(new Date());
  return { label, range: { from: subDays(to, days - 1), to } };
}

const PAGE_SIZE = 8;
const POLL_INTERVAL_MS = 3_000;
const SLOW_REPORT_AFTER_MS = 20_000;
const REPORT_TIMEOUT_MS = 5 * 60_000;

function periodLabel(report: UsageReport, allTimeLabel: string): string {
  return report.period_from
    ? `${humanReadableFormat(report.period_from)} – ${humanReadableFormat(
        report.period_to!
      )}`
    : allTimeLabel;
}

interface PendingReportRowProps {
  rangeLabel: string;
  slow: boolean;
}

function PendingReportRow({ rangeLabel, slow }: PendingReportRowProps) {
  const t = useTranslations("admin.analytics");
  return (
    <div
      className="rounded-12 border border-border-01 bg-background-tint-01 motion-safe:animate-pulse"
      data-testid="pending-report-row"
    >
      <ContentAction
        sizePreset="main-ui"
        variant="section"
        icon={SvgSpreadsheetFile}
        title={t("reports.pendingRow.title")}
        description={
          slow
            ? t("reports.pendingRow.slowDescription")
            : t("reports.pendingRow.description", { range: rangeLabel })
        }
        padding={1}
        center
        rightChildren={
          <SvgSimpleLoader
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
  const label = periodLabel(report, t("reports.period.allTime.label"));
  return (
    <div
      className={
        justArrived
          ? "rounded-12 border border-border-01 bg-background-neutral-00 motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-top-2 motion-safe:duration-500"
          : "rounded-12 border border-border-01 bg-background-neutral-00"
      }
    >
      <ContentAction
        sizePreset="main-ui"
        variant="section"
        icon={SvgSpreadsheetFile}
        title={label}
        description={t("reports.row.description", {
          requestor: report.requestor ?? t("reports.row.systemRequestor.label"),
          time: humanReadableFormatWithTime(report.time_created),
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

interface PeriodMenuItemProps {
  title: string | RichStr;
  onClick: () => void;
  icon?: IconFunctionComponent;
}

function PeriodMenuItem({ title, onClick, icon }: PeriodMenuItemProps) {
  return (
    <LineItemButton
      title={title}
      onClick={onClick}
      {...(icon && { icon })}
      rounding={3}
      selectVariant="select-heavy"
      sizePreset="main-ui"
      state="empty"
      variant="section"
      width="full"
    />
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
  const [view, setView] = useState<"presets" | "calendar">("presets");
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
    setView("presets");
    setPendingStart(undefined);
    setDraftRange(undefined);
  }

  return (
    <Popover
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen) reset();
      }}
    >
      <Popover.Trigger asChild>
        <Button icon={SvgDownloadCloud} disabled={disabled}>
          {pending
            ? t("reports.generateButton.pendingLabel")
            : t("reports.generateButton.label")}
        </Button>
      </Popover.Trigger>
      <Popover.Content
        align="end"
        side="bottom"
        width={view === "presets" ? "lg" : "fit"}
      >
        {view === "presets" ? (
          // Children must stay a flat array: Popover.Menu filters over it and
          // renders each `null` as a divider.
          <Popover.Menu>
            {[
              ...presetDays.map((preset) => (
                <Popover.Close asChild key={preset.label}>
                  <PeriodMenuItem
                    title={preset.label}
                    onClick={() =>
                      onGenerate(presetPeriod(preset.label, preset.days))
                    }
                  />
                </Popover.Close>
              )),
              <Popover.Close asChild key="all-time">
                <PeriodMenuItem
                  title={allTimeLabel}
                  onClick={() => onGenerate({ label: allTimeLabel })}
                />
              </Popover.Close>,
              null,
              <PeriodMenuItem
                key="custom"
                icon={SvgCalendar}
                title={t("reports.period.custom.label")}
                onClick={() => setView("calendar")}
              />,
            ]}
          </Popover.Menu>
        ) : (
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
                onGenerate({
                  label: `${format(from, "MMM d, y")} – ${format(to, "MMM d, y")}`,
                  range: { from, to },
                });
                setOpen(false);
                reset();
              }}
              numberOfMonths={1}
              disabled={(date) => date > new Date()}
            />
          </Section>
        )}
      </Popover.Content>
    </Popover>
  );
}

export default function UsageReports() {
  const t = useTranslations("admin.analytics");
  const [page, setPage] = useState(1);
  const [requesting, setRequesting] = useState(false);
  const [pendingReport, setPendingReport] = useState<PendingReport | null>(
    null
  );
  const [arrivedReportName, setArrivedReportName] = useState<string | null>(
    null
  );
  const slowTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reportTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const pending = pendingReport !== null;
  const {
    data: reports,
    error: listError,
    isLoading: listLoading,
    mutate,
  } = useSWR<UsageReport[]>(SWR_KEYS.usageReport, errorHandlingFetcher, {
    refreshInterval: pending ? POLL_INTERVAL_MS : 0,
  });

  useEffect(() => {
    if (listError) console.error("Failed to load usage reports:", listError);
  }, [listError]);

  function clearPendingTimers() {
    if (slowTimerRef.current) {
      clearTimeout(slowTimerRef.current);
      slowTimerRef.current = null;
    }
    if (reportTimeoutRef.current) {
      clearTimeout(reportTimeoutRef.current);
      reportTimeoutRef.current = null;
    }
  }

  useEffect(() => {
    if (!reports || !pendingReport) return;
    const completed = reports.find((report) =>
      report.report_name.includes(pendingReport.id)
    );
    if (completed) {
      setPendingReport(null);
      setArrivedReportName(completed.report_name);
      setPage(1);
      toast.success(t("reports.toasts.ready"));
      clearPendingTimers();
    }
  }, [reports, pendingReport, t]);

  useEffect(
    () => () => {
      clearPendingTimers();
      abortRef.current?.abort();
    },
    []
  );

  async function requestReport(period: ReportPeriod): Promise<void> {
    setRequesting(true);
    const abort = new AbortController();
    abortRef.current = abort;
    try {
      const reportId = await generateUsageReport(period, abort.signal);
      setPendingReport({ id: reportId, label: period.label, slow: false });
      setArrivedReportName(null);
      slowTimerRef.current = setTimeout(
        () =>
          setPendingReport((current) =>
            current ? { ...current, slow: true } : current
          ),
        SLOW_REPORT_AFTER_MS
      );
      reportTimeoutRef.current = setTimeout(() => {
        setPendingReport(null);
        toast.error(t("reports.toasts.timedOut"));
        reportTimeoutRef.current = null;
      }, REPORT_TIMEOUT_MS);
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

    // Generation already succeeded, so a failed revalidation must not surface
    // as "failed to start report generation".
    void mutate().catch((error: unknown) => {
      console.error("Failed to refresh the usage report list:", error);
    });
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
          <Text font="heading-h3">{t("reports.title")}</Text>
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

      {listLoading ? (
        <PageLoader />
      ) : listError ? (
        <MessageCard
          variant="error"
          icon={SvgX}
          title={t("reports.listError.title")}
        />
      ) : (
        <Section
          flexDirection="column"
          justifyContent="start"
          alignItems="stretch"
          gap={0.5}
          width="full"
          height="fit"
        >
          {pending && page === 1 && (
            <PendingReportRow
              rangeLabel={pendingReport.label}
              slow={pendingReport.slow}
            />
          )}
          {orderedReports.length === 0 && !pending ? (
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
