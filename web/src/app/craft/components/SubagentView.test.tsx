import React from "react";
import { render } from "@testing-library/react";
import SubagentView from "@/app/craft/components/SubagentView";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import type { BuildMessage } from "@/app/craft/types/streamingTypes";
import type { StreamItem } from "@/app/craft/types/displayTypes";

const mockBuildMessageList = jest.fn(
  (_props: {
    messages: BuildMessage[];
    streamItems: StreamItem[];
    isStreaming?: boolean;
  }) => <div data-testid="build-message-list" />
);

jest.mock("@/app/craft/components/BuildMessageList", () => ({
  __esModule: true,
  default: (props: {
    messages: BuildMessage[];
    streamItems: StreamItem[];
    isStreaming?: boolean;
  }) => mockBuildMessageList(props),
}));

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
    useBuildSessionStore
      .getState()
      .appendSubagentThinkingChunk(sessionId, subagentSessionId, "Planning.");
    useBuildSessionStore
      .getState()
      .appendSubagentResponseChunk(sessionId, subagentSessionId, "Live body.");

    render(<SubagentView subagentSessionId={subagentSessionId} />);

    expect(mockBuildMessageList).toHaveBeenCalledTimes(1);
    const props = mockBuildMessageList.mock.calls[0]![0];
    expect(props.messages).toEqual([
      expect.objectContaining({
        type: "user",
        content: "Build Space Invaders game",
      }),
    ]);
    expect(props.streamItems).toEqual([
      expect.objectContaining({
        type: "thinking",
        content: "Planning.",
        isStreaming: false,
      }),
      expect.objectContaining({
        type: "text",
        content: "Live body.",
        isStreaming: true,
      }),
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
    useBuildSessionStore
      .getState()
      .appendSubagentResponseChunk(sessionId, subagentSessionId, "Partial");
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
    expect(props.streamItems).toEqual([]);
    expect(props.messages[1]?.message_metadata?.streamItems).toEqual([
      expect.objectContaining({
        type: "text",
        content: "Complete answer",
        isStreaming: false,
      }),
    ]);
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
    useBuildSessionStore
      .getState()
      .appendSubagentResponseChunk(sessionId, subagentSessionId, "Live body.");

    render(<SubagentView subagentSessionId={subagentSessionId} />);

    const props = mockBuildMessageList.mock.calls[0]![0];
    expect(props.messages).toEqual([
      expect.objectContaining({
        type: "user",
        content: "Build Snake arcade game",
      }),
    ]);
    expect(props.streamItems).toEqual([
      expect.objectContaining({
        type: "text",
        content: "Live body.",
      }),
    ]);
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
    useBuildSessionStore
      .getState()
      .appendSubagentResponseChunk(sessionId, subagentSessionId, "Live body.");

    render(<SubagentView subagentSessionId={subagentSessionId} />);

    const props = mockBuildMessageList.mock.calls[0]![0];
    expect(props.messages[0]).toMatchObject({
      type: "user",
      content:
        "Build Snake arcade game\n\nYou are building ONE retro arcade game as a single React component.",
    });
  });
});
