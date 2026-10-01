/**
 * Icon and colour per node kind.
 *
 * Kept out of the components so the canvas, the palette and the run inspector
 * cannot drift into showing the same node three different ways.
 *
 * The icon is what tells two kinds apart; the colour groups the ones that do
 * the same sort of thing. Reaching out is info, reshaping is neutral,
 * comparing is warning, waiting is muted — so a glance at a graph reads as
 * shape before it reads as detail.
 */

import {
  SvgBranch,
  SvgCalendar,
  SvgClock,
  SvgCode,
  SvgColumn,
  SvgFilter,
  SvgGlobe,
  SvgHourglass,
  SvgLinkedDots,
  SvgListTree,
  SvgNetworkGraph,
  SvgRefreshCw,
  SvgRevert,
  SvgShareWebhook,
  SvgSparkle,
  SvgTerminal,
  SvgUserCheck,
} from "@opal/icons";
import type { FlowNodeKind, FlowNodeRunStatus } from "@/app/flows/types";

export type IconComponent = React.FunctionComponent<{
  size?: number;
  className?: string;
}>;

export interface NodeVisual {
  icon: IconComponent;
  /** Background for the icon chip. */
  chipClassName: string;
  iconClassName: string;
  /** Border shown when the node is selected. */
  accentBorderClassName: string;
}

const VISUALS = {
  HTTP: {
    icon: SvgGlobe,
    chipClassName: "bg-status-info-01",
    iconClassName: "text-status-info-05",
    accentBorderClassName: "border-status-info-05",
  },
  TRANSFORM: {
    icon: SvgCode,
    chipClassName: "bg-background-tint-03",
    iconClassName: "text-text-04",
    accentBorderClassName: "border-text-04",
  },
  CONDITION: {
    icon: SvgBranch,
    chipClassName: "bg-status-warning-01",
    iconClassName: "text-status-warning-05",
    accentBorderClassName: "border-status-warning-05",
  },
  AI: {
    icon: SvgSparkle,
    chipClassName: "bg-theme-primary-04",
    iconClassName: "text-theme-primary-06",
    accentBorderClassName: "border-theme-primary-05",
  },
  HUMAN: {
    icon: SvgUserCheck,
    chipClassName: "bg-action-selection-01",
    iconClassName: "text-action-selection-05",
    accentBorderClassName: "border-action-selection-05",
  },
  CODE: {
    icon: SvgTerminal,
    chipClassName: "bg-background-tint-03",
    iconClassName: "text-text-05",
    accentBorderClassName: "border-text-05",
  },
  LOOP: {
    icon: SvgRefreshCw,
    chipClassName: "bg-status-success-01",
    iconClassName: "text-status-success-05",
    accentBorderClassName: "border-status-success-05",
  },
  RETRY: {
    icon: SvgHourglass,
    chipClassName: "bg-background-tint-02",
    iconClassName: "text-text-03",
    accentBorderClassName: "border-text-03",
  },
  WEBHOOK: {
    icon: SvgShareWebhook,
    chipClassName: "bg-status-info-01",
    iconClassName: "text-status-info-05",
    accentBorderClassName: "border-status-info-05",
  },
  DELAY: {
    icon: SvgClock,
    chipClassName: "bg-background-tint-02",
    iconClassName: "text-text-03",
    accentBorderClassName: "border-text-03",
  },
  SCHEDULE: {
    icon: SvgCalendar,
    chipClassName: "bg-background-tint-02",
    iconClassName: "text-text-03",
    accentBorderClassName: "border-text-03",
  },
  SPLIT: {
    icon: SvgListTree,
    chipClassName: "bg-background-tint-03",
    iconClassName: "text-text-05",
    accentBorderClassName: "border-text-05",
  },
  MERGE: {
    icon: SvgLinkedDots,
    chipClassName: "bg-status-success-01",
    iconClassName: "text-status-success-05",
    accentBorderClassName: "border-status-success-05",
  },
  FILTER: {
    icon: SvgFilter,
    chipClassName: "bg-status-warning-01",
    iconClassName: "text-status-warning-05",
    accentBorderClassName: "border-status-warning-05",
  },
  PARALLEL: {
    icon: SvgColumn,
    chipClassName: "bg-status-info-01",
    iconClassName: "text-status-info-05",
    accentBorderClassName: "border-status-info-05",
  },
  SWITCH: {
    icon: SvgNetworkGraph,
    chipClassName: "bg-status-warning-01",
    iconClassName: "text-status-warning-05",
    accentBorderClassName: "border-status-warning-05",
  },
  REPEAT: {
    icon: SvgRevert,
    chipClassName: "bg-status-success-01",
    iconClassName: "text-status-success-05",
    accentBorderClassName: "border-status-success-05",
  },
} satisfies Record<FlowNodeKind, NodeVisual>;

export function visualFor(kind: FlowNodeKind): NodeVisual {
  return VISUALS[kind];
}

/**
 * Ring drawn around a node in the run inspector.
 *
 * A skipped node reads as muted rather than alarming: it is the normal
 * outcome for the branch a condition did not take, and colouring it like a
 * failure would have people chasing a bug that is not there.
 */
export function runStatusRingClassName(status: FlowNodeRunStatus): string {
  switch (status) {
    case "SUCCEEDED":
      return "border-status-success-05";
    case "FAILED":
      return "border-status-error-05";
    case "RUNNING":
      return "border-status-info-05";
    case "SKIPPED":
      return "border-border-02";
  }
}

export function isDimmedByRun(status: FlowNodeRunStatus | null): boolean {
  return status === "SKIPPED";
}
