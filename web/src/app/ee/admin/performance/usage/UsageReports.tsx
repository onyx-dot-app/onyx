"use client";

import { errorHandlingFetcher } from "@/lib/fetcher";

import { FiDownload, FiDownloadCloud } from "react-icons/fi";
import {
  DateRangePicker,
  DateRangePickerItem,
  DateRangePickerValue,
  Divider,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
  Text,
  Title,
} from "@tremor/react";
import useSWR from "swr";
import { Button } from "@tremor/react";
import { useState } from "react";
import { UsageReport } from "./types";
import { ThreeDotsLoader } from "@/components/Loading";
import Link from "next/link";
import { humanReadableFormat, humanReadableFormatWithTime } from "@/lib/time";
import { ErrorCallout } from "@/components/ErrorCallout";
import { PageSelector } from "@/components/PageSelector";

function GenerateReportInput() {
  const [dateRange, setDateRange] = useState<DateRangePickerValue | undefined>(
    undefined
  );
  const [isLoading, setIsLoading] = useState(false);

  const [errorOccurred, setErrorOccurred] = useState<Error | null>(null);

  const download = (bytes: Blob) => {
    let elm = document.createElement("a");
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
      <Title className="mb-2">Generate Usage Reports</Title>
      <Text className="mb-8">
        Generate usage statistics for users in the workspace.
      </Text>
      <DateRangePicker
        maxDate={new Date()}
        defaultValue={{
          from: undefined,
          to: undefined,
          selectValue: "allTime",
        }}
        className="mb-3"
        enableClear={false}
        selectPlaceholder="Range"
        value={dateRange}
        onValueChange={setDateRange}
      >
        <DateRangePickerItem key="lastWeek" value="lastWeek" from={lastWeek}>
          Last 7 days
        </DateRangePickerItem>
        <DateRangePickerItem key="lastMonth" value="lastMonth" from={lastMonth}>
          Last 30 days
        </DateRangePickerItem>
        <DateRangePickerItem key="lastYear" value="lastYear" from={lastYear}>
          Last year
        </DateRangePickerItem>
        <DateRangePickerItem
          key="allTime"
          value="allTime"
          from={new Date(1970, 0, 1)}
        >
          All time
        </DateRangePickerItem>
      </DateRangePicker>
      <Button
        color={"blue"}
        icon={FiDownloadCloud}
        size="xs"
        loading={isLoading}
        disabled={isLoading}
        onClick={() => requestReport()}
      >
        Generate Report
      </Button>
      <p className="mt-1 text-xs">This can take a few minutes.</p>
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
      <Title className="mb-2 mt-6 mx-auto"> Previous Reports </Title>
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
            <TableHead>
              <TableRow>
                <TableHeaderCell>Report</TableHeaderCell>
                <TableHeaderCell>Period</TableHeaderCell>
                <TableHeaderCell>Generated By</TableHeaderCell>
                <TableHeaderCell>Time Generated</TableHeaderCell>
                <TableHeaderCell>Download</TableHeaderCell>
              </TableRow>
            </TableHead>

            <TableBody>
              {paginatedReports.map((r) => (
                <TableRow key={r.report_name}>
                  <TableCell>
                    {r.report_name.split("_")[1]?.substring(0, 8) ||
                      r.report_name.substring(0, 8)}
                  </TableCell>
                  <TableCell>
                    {r.period_from
                      ? `${humanReadableFormat(
                          r.period_from
                        )} - ${humanReadableFormat(r.period_to!)}`
                      : "All time"}
                  </TableCell>
                  <TableCell>{r.requestor ?? "Auto generated"}</TableCell>
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
                    behavior: "smooth",
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
      <Divider />
      <UsageReportsTable />
    </div>
  );
}
