export interface ReportPeriod {
  label: string;
  range?: { from: Date; to: Date };
}

export interface UsageReportJob {
  report_id: string;
  status: "PENDING" | "STARTED" | "FAILURE" | "SUCCESS";
  time_created: string;
}
