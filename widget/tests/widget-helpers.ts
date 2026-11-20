import { mockTimeouts } from "./mocks";
import type { ApprovalEntry, LocalApproval } from "../src/services/approvals";
import { findPendingWait } from "../src/services/questions";
import type { ChatMessage } from "../src/types/widget-types";
import type { OnyxChatWidget } from "../src/widget";

/** The approval request that holds the chat first, if one does. */
export function findPendingApproval(
  messages: ChatMessage[],
  localApprovals: ReadonlyMap<string, LocalApproval>
): ApprovalEntry | null {
  const wait = findPendingWait(messages, localApprovals, new Map());
  return wait?.kind === "approval" ? wait.entry : null;
}

/** The widget's first waiting approval request, if one waits first. */
export function pendingApproval(widget: OnyxChatWidget): ApprovalEntry | null {
  const wait = widget["pendingWait"];
  return wait?.kind === "approval" ? wait.entry : null;
}

/** The text a template shows, without its markup or event handlers. */
export function shownText(value: unknown): string {
  if (Array.isArray(value)) return value.map(shownText).join("");
  if (typeof value === "string" || typeof value === "number")
    return String(value);
  if (typeof value === "object" && value !== null && "values" in value)
    return shownText((value as { values: unknown[] }).values);
  return "";
}

/** Resolves once `condition` holds; fails after `timeoutMs`. */
export async function waitUntil(
  condition: () => boolean,
  timeoutMs = 2_000
) {
  const deadline = Date.now() + timeoutMs;
  while (!condition()) {
    if (Date.now() > deadline) throw new Error("The condition never held");
    await Bun.sleep(1);
  }
}

/** Ends the pauses of the poll interval at once. */
export function skipPollPauses() {
  mockTimeouts((ms) => (ms === 1_000 ? 0 : ms));
}

/** A template's attribute, property and event bindings, in document order. */
export function bindings(value: unknown): { name: string; value: unknown }[] {
  if (Array.isArray(value)) return value.flatMap(bindings);
  if (typeof value !== "object" || value === null || !("values" in value))
    return [];
  // A directive result, such as keyed(), holds its arguments in `values`.
  if (!("strings" in value))
    return bindings((value as { values: unknown[] }).values);
  const { strings, values } = value as {
    strings: readonly string[];
    values: unknown[];
  };
  return values.flatMap((item, index) => {
    const name = /([.@?]?[\w-]+)=["']?$/.exec(strings[index] ?? "")?.[1];
    return name ? [{ name, value: item }] : bindings(item);
  });
}
