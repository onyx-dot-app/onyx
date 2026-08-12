export interface ChartSeries {
  label: string;
  isEmpty: boolean;
  firstDate: string | undefined;
  valueForDate: (date: string) => number;
}

export type ChartState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "empty"; message: string }
  | { status: "ready"; series: ChartSeries[] };

export interface ReportPeriod {
  label: string;
  range?: { from: Date; to: Date };
}

export interface PendingReport {
  id: string;
  label: string;
  slow: boolean;
}
