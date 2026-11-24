"use client";

import { useState } from "react";
import { FoldButton, Presence, Text } from "@opal/components";
import { TextLoader } from "@opal/loaders";
import { Section } from "@opal/layouts";
import type { IconFunctionComponent } from "@opal/types";
import { cn } from "@opal/utils";

export interface HoistedStepHeaderProps {
  /** The icon before the title. */
  icon: IconFunctionComponent;
  /** The title. A new title animates the old one out and the new one in. */
  title: string;
  /** Shimmer the title. */
  shimmer?: boolean;
  /** Whether the step is open: the chevron turns down. */
  open: boolean;
  /** Toggles the step: a click on the row or on the chevron. */
  onToggle: () => void;
  /** Called when the pointer enters or leaves the row, e.g. to fill the
   *  card around it. */
  onHoverChange?: (hovered: boolean) => void;
}

/**
 * A hoisted run card's header: its step's icon and title inline, and the
 * chevron at the end.
 * The whole row toggles the step; hovering it darkens the icon and the title
 * and lights up the chevron. A shimmering title keeps its own colours.
 */
export function HoistedStepHeader({
  icon: Icon,
  title,
  shimmer = false,
  open,
  onToggle,
  onHoverChange,
}: HoistedStepHeaderProps) {
  const [hovered, setHoveredState] = useState(false);
  const setHovered = (next: boolean) => {
    setHoveredState(next);
    onHoverChange?.(next);
  };
  const colour = cn(
    "transition-colors duration-200",
    hovered ? "text-text-04" : "text-text-03"
  );

  return (
    // Pointer convenience only: the chevron is the keyboard control.
    <div
      role="presentation"
      className="cursor-pointer flex-1 min-w-0"
      onClick={onToggle}
      onPointerEnter={() => setHovered(true)}
      onPointerLeave={() => setHovered(false)}
    >
      <Section
        flexDirection="row"
        justifyContent="between"
        gap={1}
        height="fit"
        className="font-main-ui-action min-w-0"
      >
        <Section
          flexDirection="row"
          justifyContent="start"
          gap={1}
          width="fit"
          height="fit"
          // The same inset as a collapsed run card's title, so the two line up.
          className="min-w-0 mx-(--timeline-header-text-padding-x) my-(--timeline-header-text-padding-y)"
        >
          <Icon className={cn("shrink-0 w-4 h-4", colour)} />
          {/* The inline axis: the box takes the title's width, so the icon
              and the title stay together. */}
          <Presence.Swap swapKey={title} axis="inline">
            {shimmer ? (
              <TextLoader>{title}</TextLoader>
            ) : (
              <span className={colour}>
                <Text font="main-ui-action" color="inherit">
                  {title}
                </Text>
              </span>
            )}
          </Presence.Swap>
        </Section>
        {/* md: the size of a collapsed run card's fold button. */}
        <FoldButton
          open={open}
          size="md"
          prominence="internal"
          interaction={hovered ? "hover" : undefined}
          onClick={(event) => {
            // The row toggles too; the button alone must not toggle twice.
            event.stopPropagation();
            onToggle();
          }}
        />
      </Section>
    </div>
  );
}

export default HoistedStepHeader;
