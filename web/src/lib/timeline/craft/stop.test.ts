import type { AcpToolCallStatus } from "@/lib/timeline/acp";
import {
  cancelIncomingRunningCalls,
  cancelLatestRunningCall,
} from "@/lib/timeline/craft/stop";
import type { TimelineEvent } from "@/lib/timeline/events";
import { reduceTimelineEvents } from "@/lib/timeline/reducer";

function start(toolCallId: string): TimelineEvent {
  return {
    type: "update",
    update: { sessionUpdate: "tool_call", toolCallId, title: toolCallId },
  };
}

function progress(
  toolCallId: string,
  status: AcpToolCallStatus
): TimelineEvent {
  return {
    type: "update",
    update: { sessionUpdate: "tool_call_update", toolCallId, status },
  };
}

function statuses(events: TimelineEvent[]): [string, string][] {
  return reduceTimelineEvents(events).entries.map((entry) => [
    entry.id,
    entry.status,
  ]);
}

describe("cancelIncomingRunningCalls", () => {
  it("cancels the incoming calls that are still running", () => {
    const previous = [start("done"), progress("done", "completed")];
    const incoming = [start("a"), progress("done", "completed")];
    const events = [
      ...previous,
      ...incoming,
      ...cancelIncomingRunningCalls(previous, incoming),
    ];

    expect(statuses(events)).toEqual([
      ["done", "done"],
      ["a", "stopped"],
    ]);
  });

  it("leaves running calls the incoming events do not touch", () => {
    expect(
      cancelIncomingRunningCalls([start("other")], [progress("x", "failed")])
    ).toEqual([]);
  });
});

describe("cancelLatestRunningCall", () => {
  it("cancels only the latest running call", () => {
    const previous = [start("a"), start("b"), progress("c", "completed")];
    const events = [...previous, ...cancelLatestRunningCall(previous)];

    expect(statuses(events)).toEqual([
      ["a", "streaming"],
      ["b", "stopped"],
      ["c", "done"],
    ]);
  });

  it("returns nothing when no call is running", () => {
    expect(cancelLatestRunningCall([progress("a", "completed")])).toEqual([]);
  });
});
