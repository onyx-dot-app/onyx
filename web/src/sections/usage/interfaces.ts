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
