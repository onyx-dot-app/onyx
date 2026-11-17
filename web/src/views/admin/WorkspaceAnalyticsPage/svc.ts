/** API helpers for the Workspace Analytics page. */

import { errorHandlingFetcher, type ErrorResponseBody } from "@/lib/fetcher";
import * as yup from "yup";
import { SWR_KEYS } from "@/lib/swr-keys";
import { ReportPeriod } from "@/views/admin/WorkspaceAnalyticsPage/types";

const USAGE_REPORT_URL = SWR_KEYS.usageReport;

export function usageReportDownloadUrl(reportName: string): string {
  return `${USAGE_REPORT_URL}/${reportName}`;
}

/** Starts a report build and returns the id used to recognise it in the list. */
export async function generateUsageReport(
  period: ReportPeriod,
  signal: AbortSignal
): Promise<string> {
  const reportId = crypto.randomUUID();
  const res = await fetch(USAGE_REPORT_URL, {
    method: "POST",
    credentials: "include",
    signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      period_from: period.range ? period.range.from.toISOString() : null,
      period_to: period.range ? period.range.to.toISOString() : null,
      report_id: reportId,
    }),
  });
  if (!res.ok) {
    const detail: ErrorResponseBody | null = await res
      .json()
      .catch((parseError: unknown) => {
        console.error("Usage report error response was not JSON:", parseError);
        return null;
      });
    throw new Error(
      detail?.detail ?? `Failed to start report generation: ${res.statusText}`
    );
  }
  return reportId;
}

const usageReportJobsSchema = yup
  .array(
    yup
      .object({
        report_id: yup.string().uuid().required(),
        status: yup
          .mixed<"PENDING" | "STARTED" | "FAILURE" | "SUCCESS">()
          .oneOf(["PENDING", "STARTED", "FAILURE", "SUCCESS"])
          .required(),
        time_created: yup.string().required(),
      })
      .required()
  )
  .required();

export type UsageReportJob = yup.InferType<
  typeof usageReportJobsSchema
>[number];

export async function fetchUsageReportJobs(
  url: string
): Promise<UsageReportJob[]> {
  return usageReportJobsSchema.validate(await errorHandlingFetcher(url));
}
