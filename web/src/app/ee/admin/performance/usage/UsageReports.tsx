"use client";
import i18n from "i18next";
import k from "./../../../../../i18n/keys";

import { format } from "date-fns";
import { errorHandlingFetcher } from "@/lib/fetcher";

import { FiDownload, FiDownloadCloud } from "react-icons/fi";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import { Button } from "@/components/ui/button";
import useSWR from "swr";
import { useState } from "react";
import { UsageReport } from "./types";
import { ThreeDotsLoader } from "@/components/Loading";
import Link from "next/link";
import { humanReadableFormat, humanReadableFormatWithTime } from "@/lib/time";
import { ErrorCallout } from "@/components/ErrorCallout";
import { PageSelector } from "@/components/PageSelector";
import { Separator } from "@/components/ui/separator";
import { DateRangePickerValue } from "../DateRangeSelector";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { CalendarIcon } from "lucide-react";
import { Calendar } from "@/components/ui/calendar";
import { cn } from "@/lib/utils";

function GenerateReportInput() {
  const [dateRange, setDateRange] = useState<DateRangePickerValue | undefined>(
    undefined
  );
  const [isLoading, setIsLoading] = useState(false);

  const [errorOccurred, setErrorOccurred] = useState<Error | null>(null);

  const download = (bytes: Blob) => {
    const elm = document.createElement("a");
    elm.href = URL.createObjectURL(bytes);
    elm.setAttribute("download", "usage_reports.zip");
    elm.click();
  };

  const requestReport = async () => {
    setIsLoading(true);
    setErrorOccurred(null);
    try {
      let period_from: string | null = null;
      let period_to: string | null = null;

      if (dateRange?.selectValue != "allTime" && dateRange?.from) {
        period_from = dateRange?.from?.toISOString();
        period_to = dateRange?.to?.toISOString() ?? new Date().toISOString();
      }

      const res = await fetch("/api/admin/generate-usage-report", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          period_from: period_from,
          period_to: period_to,
        }),
      });

      if (!res.ok) {
        throw Error(`Received an error: ${res.statusText}`);
      }

      const report = await res.json();
      const transfer = await fetch(
        `/api/admin/usage-report/${report.report_name}`
      );

      const bytes = await transfer.blob();
      download(bytes);
    } catch (e) {
      setErrorOccurred(e as Error);
    } finally {
      setIsLoading(false);
    }
  };

  const today = new Date();

  const lastWeek = new Date();
  lastWeek.setDate(today.getDate() - 7);

  const lastMonth = new Date();
  lastMonth.setMonth(today.getMonth() - 1);

  const lastYear = new Date();
  lastYear.setFullYear(today.getFullYear() - 1);

  return (
    <div className="mb-8">
      <Title className="mb-2">{i18n.t(k.GENERATE_USAGE_REPORTS)}</Title>
      <Text className="mb-8">{i18n.t(k.GENERATE_USAGE_STATISTICS_FOR)}</Text>
      <div className="grid gap-2 mb-3">
        <Popover>
          <PopoverTrigger asChild>
            <Button
              variant="outline"
              className={cn(
                "w-[300px] justify-start text-left font-normal",
                !dateRange && "text-muted-foreground"
              )}
            >
              <CalendarIcon className="mr-2 h-4 w-4" />
              {dateRange?.from ? (
                dateRange.to ? (
                  <>
                    {format(dateRange.from, i18n.t(k.LLL_DD_Y))} {i18n.t(k._)}{" "}
                    {format(dateRange.to, i18n.t(k.LLL_DD_Y))}
                  </>
                ) : (
                  format(dateRange.from, i18n.t(k.LLL_DD_Y))
                )
              ) : (
                <span>{i18n.t(k.PICK_A_DATE_RANGE)}</span>
              )}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="start">
            <Calendar
              initialFocus
              mode="range"
              defaultMonth={dateRange?.from}
              selected={dateRange}
              onSelect={(range) =>
                range?.from &&
                setDateRange({
                  from: range.from,
                  to: range.to ?? range.from,
                  selectValue: i18n.t(k.CUSTOM),
                })
              }
              numberOfMonths={2}
              disabled={(date) => date > new Date()}
            />

            <div className="border-t p-3">
              <Button
                variant="ghost"
                className="w-full justify-start"
                onClick={() => {
                  setDateRange({
                    from: lastWeek,
                    to: new Date(),
                    selectValue: i18n.t(k.LASTWEEK),
                  });
                }}
              >
                {i18n.t(k.LAST_DAYS1)}
              </Button>
              <Button
                variant="ghost"
                className="w-full justify-start"
                onClick={() => {
                  setDateRange({
                    from: lastMonth,
                    to: new Date(),
                    selectValue: i18n.t(k.LASTMONTH),
                  });
                }}
              >
                {i18n.t(k.LAST_DAYS)}
              </Button>
              <Button
                variant="ghost"
                className="w-full justify-start"
                onClick={() => {
                  setDateRange({
                    from: lastYear,
                    to: new Date(),
                    selectValue: i18n.t(k.LASTYEAR),
                  });
                }}
              >
                {i18n.t(k.LAST_YEAR)}
              </Button>
              <Button
                variant="ghost"
                className="w-full justify-start"
                onClick={() => {
                  setDateRange({
                    from: new Date(1970, 0, 1),
                    to: new Date(),
                    selectValue: i18n.t(k.ALLTIME),
                  });
                }}
              >
                {i18n.t(k.ALL_TIME)}
              </Button>
            </div>
          </PopoverContent>
        </Popover>
      </div>
      <Button
        color={"blue"}
        icon={FiDownloadCloud}
        size="sm"
        disabled={isLoading}
        onClick={() => requestReport()}
      >
        {i18n.t(k.GENERATE_REPORT)}
      </Button>
      <p className="mt-1 text-xs">{i18n.t(k.THIS_CAN_TAKE_A_FEW_MINUTES)}</p>
      {errorOccurred && (
        <ErrorCallout
          errorTitle="Something went wrong."
          errorMsg={errorOccurred?.toString()}
        />
      )}
    </div>
  );
}

const USAGE_REPORT_URL = "/api/admin/usage-report";

function UsageReportsTable() {
  const [page, setPage] = useState(1);
  const NUM_IN_PAGE = 10;

  const {
    data: usageReportsMetadata,
    error: usageReportsError,
    isLoading: usageReportsIsLoading,
  } = useSWR<UsageReport[]>(USAGE_REPORT_URL, errorHandlingFetcher);

  const paginatedReports = usageReportsMetadata
    ? usageReportsMetadata
        .slice(0)
        .reverse()
        .slice(NUM_IN_PAGE * (page - 1), NUM_IN_PAGE * page)
    : [];

  const totalPages = usageReportsMetadata
    ? Math.ceil(usageReportsMetadata.length / NUM_IN_PAGE)
    : 0;

  return (
    <div>
      <Title className="mb-2 mt-6 mx-auto">
        {" "}
        {i18n.t(k.PREVIOUS_REPORTS)}{" "}
      </Title>
      {usageReportsIsLoading ? (
        <div className="flex justify-center w-full">
          <ThreeDotsLoader />
        </div>
      ) : usageReportsError ? (
        <ErrorCallout
          errorTitle="Something went wrong."
          errorMsg={(usageReportsError as Error).toString()}
        />
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{i18n.t(k.REPORT)}</TableHead>
                <TableHead>{i18n.t(k.PERIOD)}</TableHead>
                <TableHead>{i18n.t(k.GENERATED_BY)}</TableHead>
                <TableHead>{i18n.t(k.TIME_GENERATED)}</TableHead>
                <TableHead>{i18n.t(k.DOWNLOAD)}</TableHead>
              </TableRow>
            </TableHeader>

            <TableBody>
              {paginatedReports.map((r) => (
                <TableRow key={r.report_name}>
                  <TableCell>
                    {r.report_name.split(i18n.t(k._32))[1]?.substring(0, 8) ||
                      r.report_name.substring(0, 8)}
                  </TableCell>
                  <TableCell>
                    {r.period_from
                      ? `${humanReadableFormat(
                          r.period_from
                        )} ${i18n.t(k._)} ${humanReadableFormat(r.period_to!)}`
                      : i18n.t(k.ALL_TIME)}
                  </TableCell>
                  <TableCell>
                    {r.requestor ?? i18n.t(k.AUTO_GENERATED)}
                  </TableCell>
                  <TableCell>
                    {humanReadableFormatWithTime(r.time_created)}
                  </TableCell>
                  <TableCell>
                    <Link
                      href={`/api/admin/usage-report/${r.report_name}`}
                      className="flex justify-center"
                    >
                      <FiDownload color="primary" />
                    </Link>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <div className="mt-3 flex">
            <div className="mx-auto">
              <PageSelector
                totalPages={totalPages}
                currentPage={page}
                onPageChange={(newPage) => {
                  setPage(newPage);
                  window.scrollTo({
                    top: 0,
                    left: 0,
                    behavior: i18n.t(k.SMOOTH),
                  });
                }}
              />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default function UsageReports() {
  return (
    <div className="mx-auto container">
      <GenerateReportInput />
      <Separator />
      <UsageReportsTable />
    </div>
  );
}
