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
 * Get a human-readable translation key for a given error code
 */
export const getErrorTitle = (errorCode?: string) => {
  switch (errorCode) {
    case "RATE_LIMIT":
      return "chat.errors.rate_limit";
    case "AUTH_ERROR":
      return "chat.errors.auth_error";
    case "PERMISSION_DENIED":
      return "chat.errors.permission_denied";
    case "CONTEXT_TOO_LONG":
      return "chat.errors.context_too_long";
    case "TOOL_CALL_FAILED":
      return "chat.errors.tool_call_failed";
    case "CONNECTION_ERROR":
      return "chat.errors.connection_error";
    case "SERVICE_UNAVAILABLE":
      return "chat.errors.service_unavailable";
    case "INIT_FAILED":
      return "chat.errors.init_failed";
    case "VALIDATION_ERROR":
      return "chat.errors.validation_error";
    case "BUDGET_EXCEEDED":
      return "chat.errors.budget_exceeded";
    case "CONTENT_POLICY":
      return "chat.errors.content_policy";
    case "BAD_REQUEST":
      return "chat.errors.bad_request";
    case "NOT_FOUND":
      return "chat.errors.not_found";
    case "API_ERROR":
      return "chat.errors.api_error";
    default:
      return "chat.errors.generic_error";
  }
};

