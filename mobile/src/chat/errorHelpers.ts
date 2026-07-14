// Human-readable title for a backend StreamingError.error_code. Ported verbatim from web's
// message/errorHelpers.tsx getErrorTitle. Mobile shows a single alert icon rather than web's
// per-code icon set (getErrorIcon), so only the title map is ported.
export function getErrorTitle(errorCode?: string | null): string {
  switch (errorCode) {
    case "RATE_LIMIT":
      return "Rate Limit Exceeded";
    case "AUTH_ERROR":
      return "Authentication Error";
    case "PERMISSION_DENIED":
      return "Permission Denied";
    case "CONTEXT_TOO_LONG":
      return "Message Too Long";
    case "TOOL_CALL_FAILED":
      return "Tool Error";
    case "CONNECTION_ERROR":
      return "Connection Error";
    case "SERVICE_UNAVAILABLE":
      return "Service Unavailable";
    case "INIT_FAILED":
      return "Initialization Error";
    case "VALIDATION_ERROR":
      return "Validation Error";
    case "BUDGET_EXCEEDED":
      return "Budget Exceeded";
    case "CONTENT_POLICY":
      return "Content Policy Violation";
    case "BAD_REQUEST":
      return "Invalid Request";
    case "NOT_FOUND":
      return "Resource Not Found";
    case "API_ERROR":
      return "API Error";
    default:
      return "Error";
  }
}
