// Mobile shows one alert icon, so web's per-code getErrorIcon is not ported — only this title map.
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
