export interface ReportPeriod {
  label: string;
  range?: { from: Date; to: Date };
}

export interface PendingReport {
  id: string;
  label: string;
  slow: boolean;
}
