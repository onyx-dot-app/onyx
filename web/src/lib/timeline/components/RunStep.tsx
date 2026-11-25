"use client";

import React, { createContext, useContext, useMemo, useState } from "react";
import { Line, Presence } from "@opal/components";
import { LineLoader } from "@opal/loaders";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { STEP_ICONS } from "@/lib/timeline/icons";
import { useRevealOnOpen } from "@/lib/chatScroll/hooks";
import type { TimelineEntryStatus } from "@/lib/timeline/types";

/** The open steps of a run card, kept while the card folds and reopens. */
export interface RunStepOpenState {
  openIds: ReadonlySet<string>;
  setOpen: (id: string, open: boolean) => void;
  /** The steps sit in a run card's scrolling list, which reveals them. */
  contained?: boolean;
}

export const RunStepOpenContext = createContext<RunStepOpenState | null>(null);

/** A run's open step ids, in the order the user opened them. */
export function useRunStepOpenState(): RunStepOpenState {
  const [openIds, setOpenIds] = useState<ReadonlySet<string>>(() => new Set());
  return useMemo(
    () => ({
      openIds,
      setOpen: (id, open) =>
        setOpenIds((previous) => {
          const next = new Set(previous);
          if (open) next.add(id);
          else next.delete(id);
          return next;
        }),
    }),
    [openIds]
  );
}

export interface RunStepProps {
  /** Keeps the step's open state in its run card. Such a step starts closed. */
  id?: string;
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
  id,
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
  const [localOpen, setLocalOpen] = useState(defaultExpanded);
  const openState = useContext(RunStepOpenContext);
  const { rowRef, onToggle } = useRevealOnOpen();
  if (hideHeader) return <>{body}</>;
  const shared = openState !== null && id !== undefined;
  const open = shared ? openState.openIds.has(id) : localOpen;
  const toggle = () => {
    // A run card's step list reveals its own steps.
    if (!(shared && openState.contained)) onToggle(!open);
    if (shared) openState.setOpen(id, !open);
    else setLocalOpen(!open);
  };

  // A failed step has finished too: it shows how it ended, e.g. "failed
  // (HTTP 401)".
  const shownTitle =
    status === "done" || status === "error" ? (doneTitle ?? title) : title;
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
    <div ref={rowRef} data-run-step-id={id}>
      <Line
        icon={statusIcon(status) ?? icon ?? STEP_ICONS.thinking}
        title={shownTitle ?? ""}
        titleKey={titleKey}
        shimmer={status === "streaming"}
        // A failed step is tinted red, as its icon already is.
        variant={status === "error" ? "error-heavy" : "default"}
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
