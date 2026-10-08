"use client";

import SvgInfo from "@opal/icons/info";
import { Tooltip } from "@opal/components/tooltip/components";
import { useOpalStrings } from "@opal/strings";
import type {
  IconFunctionComponent,
  RichStr,
  StatusVariants,
} from "@opal/types";
import { cn } from "@opal/utils";

/** The statuses an icon tooltip can show. */
type IconTooltipStatus = Extract<
  StatusVariants,
  "default" | "info" | "success" | "warning" | "error"
>;

interface IconTooltipProps {
  /** Shown at 1rem. Default: `SvgInfo`. */
  icon?: IconFunctionComponent;
  /** Colours the icon's stroke. Default: `"default"`. */
  status?: IconTooltipStatus;
  /** Shown above the icon on hover or focus. Without it, only the icon shows. */
  tooltip?: string | RichStr;
  /** The icon's name for assistive tech. Default: "More information". */
  "aria-label"?: string;
}

const STROKES: Record<IconTooltipStatus, string> = {
  default: "stroke-text-03",
  info: "stroke-status-info-05",
  success: "stroke-status-success-05",
  warning: "stroke-theme-amber-05",
  error: "stroke-status-error-05",
};

/**
 * A small icon that explains something in a tooltip. It has no click action
 * and no hover style, only a help cursor. It is a button so it takes keyboard
 * focus, and the tooltip opens on focus as well as on hover.
 */
function IconTooltip({
  icon: Icon = SvgInfo,
  status = "default",
  tooltip,
  "aria-label": ariaLabel,
}: IconTooltipProps) {
  const strings = useOpalStrings();
  const icon = <Icon size={16} className={cn("shrink-0", STROKES[status])} />;

  if (tooltip === undefined) {
    return <span className="inline-flex shrink-0 p-0.5">{icon}</span>;
  }
  return (
    <Tooltip tooltip={tooltip} side="top" align="start">
      {/* A button so keyboard users can reach the tooltip; it has no action. */}
      <button
        type="button"
        aria-label={ariaLabel ?? strings.iconTooltipLabel}
        className="inline-flex shrink-0 cursor-help rounded-04 p-0.5"
      >
        {icon}
      </button>
    </Tooltip>
  );
}

export { IconTooltip, type IconTooltipProps, type IconTooltipStatus };
