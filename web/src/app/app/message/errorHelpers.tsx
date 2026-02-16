import { AlertCircle, Clock, Lock, Wifi, Server } from "lucide-react";

/**
 * Get the appropriate icon for a given error code
 */
export const getErrorIcon = (errorCode?: string) => {
  switch (errorCode) {
    case "RATE_LIMIT":
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

/**
 * Get a human-readable title for a given error code
 */
export const getErrorTitle = (errorCode?: string) => {
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
};
