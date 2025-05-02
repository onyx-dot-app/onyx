import { TaskStatus } from "@/lib/types";

export interface TaskQueueState {
  task_id: string;
  start: string;
  end: string;
  status: TaskStatus;
  start_time: string;
}

export type StartQueryHistoryExportResponse = { request_id: string };

export type CheckQueryHistoryExportStatusResponse = {
  status: TaskStatus;
};

// The status of the spinner.
// If it's "static", then no spinning animation should be shown.
// Otherwise, the spinning animation should be shown.
export type SpinnerStatus = "static" | "spinning";
