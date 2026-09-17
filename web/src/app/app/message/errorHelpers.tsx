import { AlertCircle, Clock, Lock, Wifi, Server } from "lucide-react";

/**
 * Get the appropriate icon for a given error code
 */
export const getErrorIcon = (errorCode?: string) => {
  switch (errorCode) {
    case "RATE_LIMIT":
    case "RATE_LIMITED":
      return <Clock className="h-4 w-4" />;
    case "AUTH_ERROR":
    case "PERMISSION_DENIED":
      return <Lock className="h-4 w-4" />;
    case "CONNECTION_ERROR":
      return <Wifi className="h-4 w-4" />;
    case "SERVICE_UNAVAILABLE":
      return <Server className="h-4 w-4" />;
    case "BUDGET_EXCEEDED":
      return <AlertCircle className="h-4 w-4" />;
    default:
      return <AlertCircle className="h-4 w-4" />;
  }
};

// Error codes that have their own title. Any other code uses `default`.
const ERROR_TITLE_CODES = [
  "RATE_LIMIT",
  "RATE_LIMITED",
  "AUTH_ERROR",
  "PERMISSION_DENIED",
  "CONTEXT_TOO_LONG",
  "TOOL_CALL_FAILED",
  "CONNECTION_ERROR",
  "SERVICE_UNAVAILABLE",
  "INIT_FAILED",
  "VALIDATION_ERROR",
  "BUDGET_EXCEEDED",
  "MODEL_REFUSAL",
  "CONTENT_POLICY",
  "BAD_REQUEST",
  "NOT_FOUND",
  "API_ERROR",
] as const;

export type ErrorTitleCode = (typeof ERROR_TITLE_CODES)[number];

export type ErrorTitles = Record<ErrorTitleCode | "default", string>;

function isErrorTitleCode(value: string): value is ErrorTitleCode {
  // SAFETY: the cast only widens the argument for the readonly-array
  // `includes` signature; membership is still checked at runtime.
  return ERROR_TITLE_CODES.includes(value as ErrorTitleCode);
}

/**
 * Get a human-readable title for a given error code. The caller supplies the
 * titles because only a component can translate them.
 */
export const getErrorTitle = (
  errorCode: string | undefined,
  titles: ErrorTitles
): string =>
  errorCode && isErrorTitleCode(errorCode) ? titles[errorCode] : titles.default;
