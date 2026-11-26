export interface ReportPeriod {
  range?: { from: Date; to: Date };
}

export interface UsageReportJob {
  report_id: string;
  status: "PENDING" | "STARTED" | "FAILURE" | "SUCCESS";
  time_created: string;
}
