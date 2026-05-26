import {
  SvgTerminalSmall,
  SvgFileText,
  SvgEdit,
  SvgSearch,
  SvgGlobe,
  SvgBubbleText,
  SvgCheckSquare,
  SvgAlertCircle,
  SvgLoader,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import type {
  ToolCallKind,
  ToolCallState,
  ToolCallStatus,
} from "@/app/craft/types/displayTypes";

export function getToolIcon(kind: ToolCallKind): IconFunctionComponent {
  switch (kind) {
    case "execute":
      return SvgTerminalSmall;
    case "read":
      return SvgFileText;
    case "edit":
      return SvgEdit;
    case "search":
      return SvgSearch;
    case "task":
      return SvgBubbleText;
    case "other":
    default:
      return SvgEdit;
  }
}

export interface StatusDisplay {
  icon: IconFunctionComponent | null;
  iconClass: string;
  bgClass: string;
  showSpinner: boolean;
}

export function getStatusDisplay(status: ToolCallStatus): StatusDisplay {
  switch (status) {
    case "pending":
    case "in_progress":
      return {
        icon: null,
        iconClass: "stroke-status-info-05",
        bgClass: "bg-status-info-01 border-status-info-02",
        showSpinner: true,
      };
    case "completed":
      return {
        icon: SvgCheckSquare,
        iconClass: "stroke-status-success-05",
        bgClass: "bg-background-neutral-01 border-border-01",
        showSpinner: false,
      };
    case "failed":
      return {
        icon: SvgAlertCircle,
        iconClass: "stroke-status-error-05",
        bgClass: "bg-status-error-01 border-status-error-02",
        showSpinner: false,
      };
    case "cancelled":
      return {
        icon: SvgAlertCircle,
        iconClass: "stroke-text-02",
        bgClass: "bg-background-neutral-01 border-border-01",
        showSpinner: false,
      };
    default:
      return {
        icon: null,
        iconClass: "stroke-text-03",
        bgClass: "bg-background-neutral-01 border-border-01",
        showSpinner: false,
      };
  }
}

export { SvgLoader, SvgGlobe };

/**
 * Returns true when the tool call has completed (success or failure).
 */
export function isTerminalStatus(status: ToolCallStatus): boolean {
  return (
    status === "completed" || status === "failed" || status === "cancelled"
  );
}

/**
 * Returns the language hint to use for syntax highlighting in the body.
 * Uses the file path's extension when present, falls back to the tool kind.
 */
export function getLanguageHint(toolCall: ToolCallState): string | undefined {
  if (toolCall.kind === "execute") return "bash";
  if (toolCall.kind === "read" || toolCall.kind === "edit") {
    return toolCall.description;
  }
  return undefined;
}
