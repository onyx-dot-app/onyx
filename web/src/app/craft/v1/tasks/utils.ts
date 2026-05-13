/**
 * Small utilities for the Scheduled Tasks UI.
 */

import { formatDistanceToNowStrict, formatRelative } from "date-fns";
import type { ScheduledRunSummary } from "@/app/craft/v1/tasks/interfaces";

export function getBrowserTimezone(): string {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return tz || "UTC";
  } catch {
    return "UTC";
  }
}

export function getCommonTimezones(): string[] {
  // Use ``supportedValuesOf`` when available; fall back to a curated list.
  type ExtendedIntl = typeof Intl & {
    supportedValuesOf?: (key: string) => string[];
  };
  const ext = Intl as ExtendedIntl;
  if (typeof ext.supportedValuesOf === "function") {
    try {
      const all = ext.supportedValuesOf("timeZone");
      if (Array.isArray(all) && all.length > 0) return all;
    } catch {
      // fall through
    }
  }
  return [
    "UTC",
    "America/Los_Angeles",
    "America/Denver",
    "America/Chicago",
    "America/New_York",
    "Europe/London",
    "Europe/Berlin",
    "Europe/Paris",
    "Asia/Kolkata",
    "Asia/Singapore",
    "Asia/Tokyo",
    "Australia/Sydney",
  ];
}

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
 * A row is clickable only when the run reached a terminal state (`SUCCEEDED`
 * or `FAILED`) AND has an associated session — every other state means the
 * session view would be missing or mid-flight.
 */
export function getNonClickableReason(run: ScheduledRunSummary): string | null {
  switch (run.status) {
    case "QUEUED":
      return "This run hasn't started yet — no session to open.";
    case "RUNNING":
      return "Run still in progress — open it once it finishes.";
    case "AWAITING_APPROVAL":
      return "Run is paused awaiting approval — open it once it resumes.";
    case "SKIPPED":
      return "This run was skipped because a prior run was still in flight — no session was created.";
    case "SUCCEEDED":
    case "FAILED":
      if (!run.session_id) {
        return "This run ended before a session was created.";
      }
      return null;
  }
}
