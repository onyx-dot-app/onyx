"use client";

import React, { useState } from "react";
import { Line, Presence } from "@opal/components";
import { LineLoader } from "@opal/loaders";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { STEP_ICONS } from "@/lib/timeline/icons";
import { useRevealOnOpen } from "@/lib/chatScroll/hooks";
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
  /** Still working without a running status (e.g. Craft's thinking keeps
   *  its own icon): with no body yet, it opens onto the loading shimmer. */
  loading?: boolean;
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
  loading = false,
}: RunStepProps) {
  const [open, setOpen] = useState(defaultExpanded);
  const { rowRef, onToggle } = useRevealOnOpen();
  if (hideHeader) return <>{body}</>;
  const toggle = () => {
    onToggle(!open);
    setOpen(!open);
  };

  const shownTitle = status === "done" ? (doneTitle ?? title) : title;
  // A running step can always be opened (it still starts closed): before its
  // first content arrives, its body is a loading shimmer. A finished step
  // with nothing to show is a static row, so a click cannot open it.
  const shownBody =
    body ??
    (status === "streaming" || loading ? <LineLoader width="2/3" /> : null);
  const hasBody = shownBody !== null;
  const cardBody = hasBody
    ? {
        expandable: true as const,
        expanded: open,
        expandedContent: (
          // The shimmer swaps out for the first content; later content
          // updates in place.
          <Presence.Swap swapKey={body === null ? "loading" : "content"}>
            {shownBody}
          </Presence.Swap>
        ),
      }
    : { expandable: false as const };

  return (
    <div ref={rowRef}>
      <Line
        icon={statusIcon(status) ?? icon ?? STEP_ICONS.thinking}
        title={shownTitle ?? ""}
        titleKey={titleKey}
        shimmer={status === "streaming"}
        rightChildren={headerAccessory}
        // Filled while open; otherwise only on hover.
        filled={hasBody && open}
        onClick={hasBody ? toggle : undefined}
        // The body starts under the title text.
        bodyInset="title"
        {...cardBody}
      />
    </div>
  );
}

export default RunStep;
