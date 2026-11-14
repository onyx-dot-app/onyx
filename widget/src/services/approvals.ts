/**
 * Tool-call approvals - status logic and copy for the approval card
 */

import type {
  ApprovalDecisionResponse,
  ToolApprovalRequest,
} from "@/types/api-types";
import type { ChatMessage } from "@/types/widget-types";

/** `error_code` of the 409 a send gets while the chat waits for a decision. */
export const APPROVAL_PENDING_ERROR_CODE = "APPROVAL_PENDING";

export type ApprovalDecision = "approve_once" | "approve_session" | "reject";

export type ApprovalOutcome =
  | "approved"
  | "approved_for_chat"
  | "rejected"
  | "expired"
  | "disabled"
  | "cancelled";

/**
 * "approvedForSession": approved by a grant for the chat's later requests of
 * the same tool. "disabled": an approval found the tool disabled by a policy,
 * so the call did not run. "closed": nothing waits for a decision any more,
 * and the outcome is unknown.
 */
export type ApprovalStatus =
  | "pending"
  | "approved"
  | "approvedForSession"
  | "rejected"
  | "expired"
  | "disabled"
  | "closed";

export interface ApprovalEntry {
  request: ToolApprovalRequest;
  /** Null until the resolution packet arrives. */
  outcome: ApprovalOutcome | null;
}

const OUTCOMES: ReadonlySet<string> = new Set<ApprovalOutcome>([
  "approved",
  "approved_for_chat",
  "rejected",
  "expired",
  "disabled",
  "cancelled",
]);

/** A known outcome, or null for a value this widget does not know. */
export function readOutcome(value: unknown): ApprovalOutcome | null {
  return typeof value === "string" && OUTCOMES.has(value)
    ? (value as ApprovalOutcome)
    : null;
}

/**
 * The resolution packet decides the status. Before it arrives, a decision from
 * this widget decides it; a stopped response closes the request. A response
 * stops only when the server ends it, not when this widget loses its stream.
 * The deadline never decides: the server resolves an expired request.
 */
export function approvalStatus(
  entry: ApprovalEntry,
  localStatus: ApprovalStatus | undefined,
  stopped: boolean
): ApprovalStatus {
  switch (entry.outcome) {
    case null:
      return localStatus ?? (stopped ? "closed" : "pending");
    case "approved_for_chat":
      return "approvedForSession";
    case "cancelled":
      return "closed";
    default:
      return entry.outcome;
  }
}

/** The status the server's answer to a decision from this widget shows. */
export function decidedStatus(
  response: ApprovalDecisionResponse
): ApprovalStatus {
  if (response.decided_via === "POLICY") return "disabled";
  if (response.decision === "REJECTED") return "rejected";
  return response.decided_via === "SESSION_GRANT"
    ? "approvedForSession"
    : "approved";
}

/** The first request that still waits for this user. */
export function findPendingApproval(
  messages: ChatMessage[],
  localStatuses: ReadonlyMap<string, ApprovalStatus>
): ApprovalEntry | null {
  for (const message of messages) {
    const pending = message.approvals?.find(
      (entry) =>
        approvalStatus(
          entry,
          localStatuses.get(entry.request.approval_id),
          !message.isStreaming
        ) === "pending"
    );
    if (pending) return pending;
  }
  return null;
}

/** The one-line record of a decided request, or null while it waits. */
export function approvalRecord(
  status: ApprovalStatus,
  toolName: string
): string | null {
  switch (status) {
    case "pending":
      return null;
    case "approved":
      return `Approved: ${toolName}`;
    case "approvedForSession":
      return `Approved for this chat: ${toolName}`;
    case "rejected":
      return `Not approved: ${toolName}`;
    case "expired":
      return `Timed out: ${toolName}`;
    case "disabled":
      return `Disabled: ${toolName}`;
    case "closed":
      return `No longer waiting: ${toolName}`;
  }
}

/** "Approve by 3:45 PM" in the visitor's locale, or null for a bad date. */
export function approvalDeadline(
  expiresAt: string,
  locale?: string
): string | null {
  const date = new Date(expiresAt);
  if (Number.isNaN(date.getTime())) return null;
  const time = new Intl.DateTimeFormat(locale, {
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
  return `Approve by ${time}`;
}

// Limits on a tool call's arguments, which come from the model, before the
// widget stores them in sessionStorage or renders them. Lengths count UTF-16
// code units, the unit sessionStorage and the DOM store. The per-value limits
// keep one large value from hiding the arguments after it.
const MAX_ARGUMENT_STRING_CHARS = 2_000;
const MAX_ARGUMENT_CHARS = 20_000;
const MAX_ARGUMENT_ITEMS = 50;
// Values in the whole argument tree, containers included
const MAX_ARGUMENT_VALUES = 500;
const MAX_ARGUMENT_DEPTH = 8;
const OMITTED = "…";

/**
 * A copy of the arguments within the limits. Past a limit, a string ends in
 * "…", a container lists its first values and then "…", and a deeper value
 * becomes "…".
 */
export function boundArguments(
  args: Record<string, unknown>
): Record<string, unknown> {
  let chars = 0;
  let values = 0;
  const full = () =>
    values >= MAX_ARGUMENT_VALUES || chars >= MAX_ARGUMENT_CHARS;
  const clip = (text: string): string => {
    const room = Math.min(
      MAX_ARGUMENT_STRING_CHARS,
      MAX_ARGUMENT_CHARS - chars
    );
    chars += Math.min(text.length, room);
    return text.length > room ? `${text.slice(0, room)}${OMITTED}` : text;
  };
  const bound = (value: unknown, depth: number): unknown => {
    values += 1;
    if (typeof value === "string") return clip(value);
    if (value === null || typeof value !== "object") return value;
    if (depth >= MAX_ARGUMENT_DEPTH) return OMITTED;
    if (Array.isArray(value)) {
      const items: unknown[] = [];
      for (const item of value) {
        if (items.length >= MAX_ARGUMENT_ITEMS || full()) {
          items.push(OMITTED);
          break;
        }
        items.push(bound(item, depth + 1));
      }
      return items;
    }
    const entries: [string, unknown][] = [];
    for (const key in value) {
      if (entries.length >= MAX_ARGUMENT_ITEMS || full()) {
        entries.push([OMITTED, OMITTED]);
        break;
      }
      entries.push([
        clip(key),
        bound((value as Record<string, unknown>)[key], depth + 1),
      ]);
    }
    // fromEntries defines own keys, so a "__proto__" key stays plain data.
    return Object.fromEntries(entries);
  };
  return bound(args ?? {}, 0) as Record<string, unknown>;
}

// Past this length a string value shows Show more.
const STRING_TRUNCATE_AT = 300;
// Past this many lines a JSON value shows Show more.
const JSON_TRUNCATE_AT_LINES = 8;

export interface ArgumentRow {
  key: string;
  text: string;
  /** Null when the value shows in full. */
  preview: string | null;
  mono: boolean;
}

/**
 * One row per top-level argument. Primitive arrays join to one line; objects
 * and other arrays show as JSON.
 */
export function argumentRows(args: Record<string, unknown>): ArgumentRow[] {
  const rows: ArgumentRow[] = [];
  for (const [key, value] of Object.entries(args ?? {})) {
    if (value === null || value === undefined) continue;
    const primitiveArray =
      Array.isArray(value) &&
      value.length > 0 &&
      value.every((v) => ["string", "number", "boolean"].includes(typeof v));
    if (typeof value === "object" && !primitiveArray) {
      const text = JSON.stringify(value, null, 2);
      const lines = text.split("\n");
      rows.push({
        key,
        text,
        preview:
          lines.length > JSON_TRUNCATE_AT_LINES
            ? `${lines.slice(0, JSON_TRUNCATE_AT_LINES).join("\n")}\n…`
            : null,
        mono: true,
      });
      continue;
    }
    const text = primitiveArray
      ? (value as unknown[]).map(String).join(", ")
      : String(value);
    rows.push({
      key,
      text,
      preview:
        text.length > STRING_TRUNCATE_AT
          ? `${text.slice(0, STRING_TRUNCATE_AT)}…`
          : null,
      mono: false,
    });
  }
  return rows;
}
