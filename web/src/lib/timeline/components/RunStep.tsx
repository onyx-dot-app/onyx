"use client";

import React, { useState } from "react";
import { Line } from "@opal/components";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { STEP_ICONS } from "@/lib/timeline/icons";
import type { TimelineEntryStatus } from "@/lib/timeline/types";

export interface RunStepProps {
  status: TimelineEntryStatus;
  /** The step kind's icon; a running or failed step shows its status. */
  icon?: IconFunctionComponent;
  /** The title while the step runs, and after it fails or is stopped. */
  title?: string | RichStr;
  /** The title once the step is done. Defaults to `title`. */
  doneTitle?: string | RichStr;
  /** The title's identity: a new key swaps the title. Defaults to its text. */
  titleKey?: React.Key;
  /** Rendered at the end of the header, before the chevron. */
  headerAccessory?: React.ReactNode;
  /** The step's body; `null` for a step with nothing to show. */
  body?: React.ReactNode;
  /** Start open. */
  defaultExpanded?: boolean;
  /** The body has no header (the body is its own control). */
  hideHeader?: boolean;
}

function statusIcon(
  status: TimelineEntryStatus
): IconFunctionComponent | undefined {
  if (status === "streaming") return STEP_ICONS.running;
  if (status === "error") return STEP_ICONS.failed;
  // A stopped step must not look finished.
  if (status === "stopped") return STEP_ICONS.stopped;
  return undefined;
}

/**
 * One step of a run, the same everywhere: on its own as a hoisted run card,
 * or inside a collapsed run card. It is an Opal `Line` card whose title is
 * the step's (a spinner and a shimmer while it runs, its done title once it
 * finishes), with a chevron that opens its body.
 */
export function RunStep({
  status,
  icon,
  title,
  doneTitle,
  titleKey,
  headerAccessory,
  body = null,
  defaultExpanded = false,
  hideHeader = false,
}: RunStepProps) {
  const [open, setOpen] = useState(defaultExpanded);
  if (hideHeader) return <>{body}</>;

  const shownTitle = status === "done" ? (doneTitle ?? title) : title;
  const cardBody =
    body !== null
      ? {
          expandable: true as const,
          expanded: open,
          expandedContent: body,
        }
      : { expandable: false as const };

  return (
    <Line
      icon={statusIcon(status) ?? icon ?? STEP_ICONS.thinking}
      title={shownTitle ?? ""}
      titleKey={titleKey}
      shimmer={status === "streaming"}
      rightChildren={headerAccessory}
      // Filled while open; otherwise only on hover.
      filled={open}
      onClick={() => setOpen((prev) => !prev)}
      // The body starts under the title text.
      bodyInset="title"
      {...cardBody}
    />
  );
}

export default RunStep;
