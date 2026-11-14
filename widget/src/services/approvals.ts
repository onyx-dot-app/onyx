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

/** `stop_reason` of a stream that stops while the response waits for decisions. */
export const AWAITING_APPROVAL_STOP_REASON = "awaiting_approval";

export type ApprovalDecision = "approve_once" | "approve_session" | "reject";

export type ApprovalOutcome =
  | "approved"
  | "approved_for_chat"
  | "rejected"
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
 * this widget decides it; a response that ended closes the request.
 */
export function approvalStatus(
  entry: ApprovalEntry,
  localStatus: ApprovalStatus | undefined,
  ended: boolean
): ApprovalStatus {
  switch (entry.outcome) {
    case null:
      return localStatus ?? (ended ? "closed" : "pending");
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

/**
 * The server ended the response. A stop while it waits for decisions does not
 * end it, and neither does a stream this widget lost.
 */
export function responseEnded(message: ChatMessage): boolean {
  return !message.isStreaming && !message.awaitingApproval;
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
          responseEnded(message)
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
    case "disabled":
      return `Disabled: ${toolName}`;
    case "closed":
      return `No longer waiting: ${toolName}`;
  }
}

// Past this length a string value shows Show more.
const STRING_TRUNCATE_AT = 300;
// Past this many lines or characters a JSON value shows Show more.
const JSON_TRUNCATE_AT_LINES = 8;
const JSON_TRUNCATE_AT_CHARS = 1_000;
/** Past this many rows the card shows Show all arguments. */
export const ARGUMENT_ROWS_SHOWN = 20;

export interface ArgumentRow {
  key: string;
  text: string;
  /** Null when the value shows in full. */
  preview: string | null;
  mono: boolean;
}

/**
 * One row per top-level argument, with the full text and a short preview.
 * Primitive arrays join to one line; objects and other arrays show as JSON.
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
      const head = text
        .slice(0, JSON_TRUNCATE_AT_CHARS)
        .split("\n")
        .slice(0, JSON_TRUNCATE_AT_LINES)
        .join("\n");
      rows.push({
        key,
        text,
        preview: head.length < text.length ? `${head}\n…` : null,
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
