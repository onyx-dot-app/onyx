import React from "react";
import { render } from "@tests/setup/test-utils";
import SubagentView from "@/app/craft/components/SubagentView";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { reduceTimelineEvents } from "@/lib/timeline/reducer";
import type { BuildMessage } from "@/app/craft/types/streamingTypes";
import type { TimelineEvent } from "@/lib/timeline/events";

const mockBuildMessageList = jest.fn(
  (_props: {
    messages: BuildMessage[];
    timelineEvents: TimelineEvent[];
    isStreaming?: boolean;
  }) => <div data-testid="build-message-list" />
);

jest.mock("@/app/craft/components/BuildMessageList", () => ({
  __esModule: true,
  default: (props: {
    messages: BuildMessage[];
    timelineEvents: TimelineEvent[];
    isStreaming?: boolean;
  }) => mockBuildMessageList(props),
}));

function text(content: string): TimelineEvent {
  return {
    type: "update",
    update: {
      sessionUpdate: "agent_message_chunk",
      content: { type: "text", text: content },
    },
  };
}

function thought(content: string): TimelineEvent {
  return {
    type: "update",
    update: {
      sessionUpdate: "agent_thought_chunk",
      content: { type: "text", text: content },
    },
  };
}

function appendEvents(
  sessionId: string,
  subagentSessionId: string,
  events: TimelineEvent[]
) {
  useBuildSessionStore
    .getState()
    .appendSubagentTimelineEvents(sessionId, subagentSessionId, events);
}

describe("SubagentView", () => {
  beforeEach(() => {
    mockBuildMessageList.mockClear();
    useBuildSessionStore.setState({
      currentSessionId: null,
      sessions: new Map(),
    } as never);
  });

  it("renders the running subagent turn through the live stream path", () => {
    const sessionId = "parent-session";
    const subagentSessionId = "child-session";

    useBuildSessionStore.getState().createSession(sessionId, {
      status: "active",
      isLoaded: true,
    });
    useBuildSessionStore.getState().setCurrentSession(sessionId);
    useBuildSessionStore
      .getState()
      .seedSubagentMeta(
        sessionId,
        subagentSessionId,
        "task-call",
        "task",
        "Build Space Invaders game",
        "Build Space Invaders game"
      );
    appendEvents(sessionId, subagentSessionId, [
      thought("Planning."),
      text("Live body."),
    ]);

    render(<SubagentView subagentSessionId={subagentSessionId} />);

    expect(mockBuildMessageList).toHaveBeenCalledTimes(1);
    const props = mockBuildMessageList.mock.calls[0]![0];
    expect(props.messages).toEqual([
      expect.objectContaining({
        type: "user",
        content: "Build Space Invaders game",
      }),
    ]);
    expect(props.timelineEvents).toEqual([
      thought("Planning."),
      text("Live body."),
    ]);
    expect(props.isStreaming).toBe(true);
  });

  it("renders the final completion response instead of stale streamed text", () => {
    const sessionId = "parent-session";
    const subagentSessionId = "child-session";

    useBuildSessionStore.getState().createSession(sessionId, {
      status: "active",
      isLoaded: true,
    });
    useBuildSessionStore.getState().setCurrentSession(sessionId);
    useBuildSessionStore
      .getState()
      .seedSubagentMeta(
        sessionId,
        subagentSessionId,
        "task-call",
        "task",
        "Build Space Invaders game",
        "Build Space Invaders game"
      );
    appendEvents(sessionId, subagentSessionId, [text("Partial")]);
    useBuildSessionStore
      .getState()
      .markSubagentComplete(
        sessionId,
        subagentSessionId,
        "done",
        "Complete answer"
      );

    render(<SubagentView subagentSessionId={subagentSessionId} />);

    expect(mockBuildMessageList).toHaveBeenCalledTimes(1);
    const props = mockBuildMessageList.mock.calls[0]![0];
    expect(props.timelineEvents).toEqual([]);
    const events = props.messages[1]?.timelineEvents ?? [];
    const entries = reduceTimelineEvents(events).entries;
    expect(entries).toHaveLength(1);
    expect(entries[0]?.payload).toEqual({
      kind: "message",
      content: [{ type: "text", text: "Complete answer" }],
    });
    expect(props.isStreaming).toBe(false);
  });

  it("uses the subagent name as the dispatch prompt when the prompt is missing", () => {
    const sessionId = "parent-session";
    const subagentSessionId = "child-session";

    useBuildSessionStore.getState().createSession(sessionId, {
      status: "active",
      isLoaded: true,
    });
    useBuildSessionStore.getState().setCurrentSession(sessionId);
    useBuildSessionStore
      .getState()
      .seedSubagentMeta(
        sessionId,
        subagentSessionId,
        "task-call",
        "task",
        "Build Snake arcade game",
        ""
      );
    appendEvents(sessionId, subagentSessionId, [text("Live body.")]);

    render(<SubagentView subagentSessionId={subagentSessionId} />);

    const props = mockBuildMessageList.mock.calls[0]![0];
    expect(props.messages).toEqual([
      expect.objectContaining({
        type: "user",
        content: "Build Snake arcade game",
      }),
    ]);
    expect(props.timelineEvents).toEqual([text("Live body.")]);
  });

  it("keeps the task name visible when the stored prompt is longer", () => {
    const sessionId = "parent-session";
    const subagentSessionId = "child-session";

    useBuildSessionStore.getState().createSession(sessionId, {
      status: "active",
      isLoaded: true,
    });
    useBuildSessionStore.getState().setCurrentSession(sessionId);
    useBuildSessionStore
      .getState()
      .seedSubagentMeta(
        sessionId,
        subagentSessionId,
        "task-call",
        "task",
        "Build Snake arcade game",
        "You are building ONE retro arcade game as a single React component."
      );
    appendEvents(sessionId, subagentSessionId, [text("Live body.")]);

    render(<SubagentView subagentSessionId={subagentSessionId} />);

    const props = mockBuildMessageList.mock.calls[0]![0];
    expect(props.messages[0]).toMatchObject({
      type: "user",
      content:
        "Build Snake arcade game\n\nYou are building ONE retro arcade game as a single React component.",
    });
  });
});
