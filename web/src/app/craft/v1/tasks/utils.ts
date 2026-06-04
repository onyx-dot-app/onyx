/**
 * Small utilities for the Scheduled Tasks UI.
 */

import { formatDistanceToNowStrict, formatRelative } from "date-fns";
import type {
  ScheduledRunContextResponse,
  ScheduledRunSummary,
  ScheduledTaskRunStatus,
} from "@/app/craft/v1/tasks/interfaces";

export function formatRelativeShort(isoOrDate: string | Date | null): string {
  if (!isoOrDate) return "—";
  const date = typeof isoOrDate === "string" ? new Date(isoOrDate) : isoOrDate;
  if (Number.isNaN(date.getTime())) return "—";
  const diffMs = Math.abs(date.getTime() - Date.now());
  // Within a minute, say "now"
  if (diffMs < 60_000) return "just now";
  const suffix = date.getTime() > Date.now() ? "from now" : "ago";
  return `${formatDistanceToNowStrict(date)} ${suffix}`;
}

export function formatAbsolute(isoOrDate: string | Date | null): string {
  if (!isoOrDate) return "—";
  const date = typeof isoOrDate === "string" ? new Date(isoOrDate) : isoOrDate;
  if (Number.isNaN(date.getTime())) return "—";
  return formatRelative(date, new Date());
}

export function formatDurationMs(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return "<1s";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rs = s % 60;
  if (m < 60) return rs === 0 ? `${m}m` : `${m}m ${rs}s`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return rm === 0 ? `${h}h` : `${h}h ${rm}m`;
}

export function formatRunDuration(
  startedAt: string | null,
  finishedAt: string | null
): string {
  if (!startedAt || !finishedAt) return "—";
  const start = new Date(startedAt).getTime();
  const end = new Date(finishedAt).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "—";
  return formatDurationMs(end - start);
}

/**
 * Returns a human-readable reason a run row can't be opened as a session,
 * or `null` when the row is clickable.
 *
 * A row is clickable once there is a session to open. Queued rows have not
 * created one yet; skipped rows deliberately never create one.
 */
export function getNonClickableReason(run: ScheduledRunSummary): string | null {
  if (
    run.status === "RUNNING" ||
    run.status === "AWAITING_APPROVAL" ||
    run.status === "SUCCEEDED" ||
    run.status === "FAILED"
  ) {
    return run.session_id ? null : "This run has not created a session yet.";
  }

  switch (run.status) {
    case "QUEUED":
      return "This run hasn't started yet — no session to open.";
    case "SKIPPED":
      return "This run was skipped because a prior run was still in flight — no session was created.";
  }
  return null;
}

export function isScheduledRunInFlight(
  status: ScheduledTaskRunStatus
): boolean {
  return status === "RUNNING" || status === "AWAITING_APPROVAL";
}

export function isScheduledRunContextInFlight(
  context: ScheduledRunContextResponse | null | undefined
): boolean {
  return context ? isScheduledRunInFlight(context.status) : false;
}
