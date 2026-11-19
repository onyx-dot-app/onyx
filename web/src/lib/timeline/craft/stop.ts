import type { TimelineEvent } from "@/lib/timeline/events";
import { reduceTimelineEvents } from "@/lib/timeline/reducer";

/**
 * Craft marks tool calls cancelled when the user presses Stop. ACP has no
 * cancelled status, so these helpers send it as an explicit update with
 * `_meta.onyx.cancelled`.
 */

function cancelEvent(toolCallId: string): TimelineEvent {
  return {
    type: "update",
    update: {
      sessionUpdate: "tool_call_update",
      toolCallId,
      _meta: { onyx: { cancelled: true } },
    },
  };
}

function runningToolCallIds(events: readonly TimelineEvent[]): string[] {
  return reduceTimelineEvents(events)
    .entries.filter(
      (entry) => entry.payload.kind === "tool" && entry.status === "streaming"
    )
    .map((entry) => entry.id);
}

/**
 * While a Stop is in flight, a tool call that `incoming` starts or updates and
 * that is still running is cancelled.
 */
export function cancelIncomingRunningCalls(
  previous: readonly TimelineEvent[],
  incoming: readonly TimelineEvent[]
): TimelineEvent[] {
  const touched = new Set(
    incoming.flatMap((event) =>
      event.type === "update" &&
      (event.update.sessionUpdate === "tool_call" ||
        event.update.sessionUpdate === "tool_call_update")
        ? [event.update.toolCallId]
        : []
    )
  );
  if (touched.size === 0) return [];
  return runningToolCallIds([...previous, ...incoming])
    .filter((id) => touched.has(id))
    .map(cancelEvent);
}

/** Cancels the latest tool call that is still running, if there is one. */
export function cancelLatestRunningCall(
  events: readonly TimelineEvent[]
): TimelineEvent[] {
  const latest = runningToolCallIds(events).at(-1);
  return latest === undefined ? [] : [cancelEvent(latest)];
}
