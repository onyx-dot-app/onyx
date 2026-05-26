"use client";

import { cn } from "@opal/utils";
import { SvgChevronDown } from "@opal/icons";
import { Text } from "@opal/components";
import type { IconFunctionComponent } from "@opal/types";
import SkillBadge from "@/app/craft/components/tool-cards/SkillBadge";
import {
  getToolIcon,
  getStatusDisplay,
  SvgLoader,
} from "@/app/craft/components/tool-cards/helpers";
import type {
  ToolCardCommonProps,
  ToolCardDensity,
} from "@/app/craft/components/tool-cards/interfaces";

interface ToolCardHeaderProps extends ToolCardCommonProps {
  isOpen: boolean;
  /** Optional override for the tool icon (per-body customization) */
  iconOverride?: IconFunctionComponent;
  /** Secondary line under the title (e.g., the command for bash) */
  secondaryLine?: React.ReactNode;
  /** Optional skill name to render as a SkillBadge in the header */
  skillName?: string;
  /** Right-side metadata slot (e.g., "+3 -1" stats, "exit 0", duration) */
  rightMeta?: React.ReactNode;
}

function paddingForDensity(density: ToolCardDensity): string {
  return density === "compact" ? "py-1.5 pl-2 pr-3" : "px-3 py-2";
}

function iconSizeForDensity(density: ToolCardDensity): string {
  return density === "compact" ? "size-3.5" : "size-4";
}

/**
 * ToolCardHeader - Shared header chrome for tool cards.
 *
 * Renders status icon + tool icon + title + description + chevron, with
 * optional skill badge, secondary line (e.g., the command for bash), and a
 * right-aligned metadata slot.
 */
export default function ToolCardHeader({
  toolCall,
  density = "comfortable",
  isOpen,
  iconOverride,
  secondaryLine,
  skillName,
  rightMeta,
}: ToolCardHeaderProps) {
  const statusDisplay = getStatusDisplay(toolCall.status);
  const StatusIcon = statusDisplay.icon;
  const ToolIcon = iconOverride ?? getToolIcon(toolCall.kind);
  const iconSize = iconSizeForDensity(density);
  const titleFont = density === "compact" ? "main-ui-body" : "main-ui-action";

  return (
    <div
      className={cn("w-full flex flex-col gap-1", paddingForDensity(density))}
    >
      <div className="flex items-center justify-between gap-2 w-full">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {statusDisplay.showSpinner ? (
            <SvgLoader
              className={cn(
                iconSize,
                "stroke-status-info-05 animate-spin shrink-0"
              )}
            />
          ) : StatusIcon ? (
            <StatusIcon
              className={cn(iconSize, "shrink-0", statusDisplay.iconClass)}
            />
          ) : (
            <ToolIcon className={cn(iconSize, "stroke-text-03 shrink-0")} />
          )}

          <Text font={titleFont} color="text-04" nowrap>
            {toolCall.title}
          </Text>

          {toolCall.description && (
            <span className="truncate min-w-0">
              <Text font="main-ui-body" color="text-03" nowrap>
                {toolCall.description}
              </Text>
            </span>
          )}

          {skillName && <SkillBadge name={skillName} />}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {rightMeta}
          <SvgChevronDown
            className={cn(
              iconSize,
              "stroke-text-03 transition-transform duration-150 shrink-0",
              !isOpen && "-rotate-90"
            )}
          />
        </div>
      </div>

      {secondaryLine && <div className="pl-6">{secondaryLine}</div>}
    </div>
  );
}
