import * as NodeUtil from "node:util";
import { BrowserControlInterrupted } from "./SessionControl.ts";

export type ErrorCode =
  | "human_control"
  | "tab_not_found"
  | "tab_required"
  | "dialog_pending"
  | "stale_ref"
  | "timeout"
  | "invalid_argument"
  | "not_editable"
  | "tab_limit"
  | "failed";

export const HUMAN_CONTROL_MESSAGE =
  "A human controls this tab. Open a new tab with browser_open(new_tab=true) to keep working, or ask the user to release control.";

export const isTimeout = (cause: unknown): cause is Error =>
  cause instanceof Error && cause.name === "TimeoutError";

export class OperationError extends Error {
  readonly code: ErrorCode;

  constructor(code: ErrorCode, message: string) {
    super(message);
    this.name = "OperationError";
    this.code = code;
  }
}

/** Playwright puts why an element was not actionable in its call log, below the first line. */
export const withActionabilityReason = (message: string, cause: Error) => {
  const reason = NodeUtil.stripVTControlCharacters(cause.message)
    .split("\n")
    .map((line) => line.trim())
    .findLast((line) => line.startsWith("- element is "))
    ?.slice(2);
  return reason === undefined ? message : `${message} Playwright last saw: ${reason}.`;
};

export const toOperationError = (cause: unknown): OperationError => {
  if (cause instanceof OperationError) return cause;
  if (cause instanceof BrowserControlInterrupted) {
    switch (cause.reason) {
      case "humanControl":
        return new OperationError("human_control", HUMAN_CONTROL_MESSAGE);
      case "closed":
        return new OperationError("tab_not_found", cause.message);
      default:
        return new OperationError("human_control", cause.message);
    }
  }
  const message = cause instanceof Error ? cause.message : String(cause);
  const firstLine = message.split("\n")[0] ?? message;
  if (isTimeout(cause)) {
    return new OperationError("timeout", withActionabilityReason(firstLine, cause));
  }
  if (/while parsing selector|Unknown engine|Unexpected token/i.test(message)) {
    return new OperationError("invalid_argument", firstLine);
  }
  if (/not an <input>|not editable|not an editable/i.test(message)) {
    return new OperationError("not_editable", firstLine);
  }
  return new OperationError("failed", firstLine);
};
