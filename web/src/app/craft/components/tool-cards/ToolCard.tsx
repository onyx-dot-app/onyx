"use client";

import { useState, type ReactNode } from "react";
import { cn } from "@opal/utils";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";
import { getStatusDisplay } from "@/app/craft/components/tool-cards/helpers";
import ToolCardHeader from "@/app/craft/components/tool-cards/ToolCardHeader";
import type {
  ToolCardCommonProps,
  ToolCardDensity,
} from "@/app/craft/components/tool-cards/interfaces";
import type { IconFunctionComponent } from "@opal/types";

interface ToolCardProps extends ToolCardCommonProps {
  /** Rendered body content (per-tool specialization) */
  children: ReactNode;
  /** Optional tool-icon override for the header */
  iconOverride?: IconFunctionComponent;
  /** Optional secondary line under the title (e.g., the command for bash) */
  secondaryLine?: ReactNode;
  /** Optional skill name to render as a SkillBadge in the header */
  skillName?: string;
  /** Optional right-side metadata (stats, exit code, duration) */
  rightMeta?: ReactNode;
}

function containerStylesForDensity(
  density: ToolCardDensity,
  bgClass: string
): string {
  if (density === "compact") {
    return cn(
      "w-full rounded-md overflow-hidden transition-colors",
      "hover:bg-background-tint-02"
    );
  }
  return cn(
    "w-full border-[0.5px] rounded-lg overflow-hidden transition-colors",
    "hover:bg-background-tint-02",
    bgClass
  );
}

function bodyPaddingForDensity(density: ToolCardDensity): string {
  return density === "compact" ? "pl-6 pr-2 pb-2" : "px-3 pb-3 pt-0";
}

/**
 * ToolCard - Base container for per-tool rendering.
 *
 * Two density variants:
 *  - "comfortable" — full bordered pill (formerly ToolCallPill)
 *  - "compact" — single hover row used inside WorkingPill (formerly WorkingLine)
 *
 * Body content is supplied by per-tool body components (BashBody, DiffBody, ...).
 * Defaults to closed for terminal-status calls and open for in-progress calls.
 */
export default function ToolCard({
  toolCall,
  density = "comfortable",
  defaultOpen,
  children,
  iconOverride,
  secondaryLine,
  skillName,
  rightMeta,
}: ToolCardProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen ?? false);
  const statusDisplay = getStatusDisplay(toolCall.status);

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <div
        className={containerStylesForDensity(density, statusDisplay.bgClass)}
      >
        <CollapsibleTrigger asChild>
          <button
            className={cn(
              "w-full text-left transition-colors",
              density === "compact" && "rounded-md",
              density === "comfortable" && "rounded-t-lg"
            )}
          >
            <ToolCardHeader
              toolCall={toolCall}
              density={density}
              isOpen={isOpen}
              iconOverride={iconOverride}
              secondaryLine={secondaryLine}
              skillName={skillName}
              rightMeta={rightMeta}
            />
          </button>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <div className={bodyPaddingForDensity(density)}>{children}</div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
