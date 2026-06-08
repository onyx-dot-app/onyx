import { act, renderHook } from "@testing-library/react";

import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { useBuildStreaming } from "@/app/craft/hooks/useBuildStreaming";
import type { StreamItem } from "@/app/craft/types/displayTypes";
import {
  processSSEStream,
  sendMessageStream,
} from "@/app/craft/services/apiServices";

jest.mock("swr", () => ({
  useSWRConfig: () => ({ mutate: jest.fn() }),
}));

jest.mock("@/app/craft/services/apiServices", () => ({
  RateLimitError: class RateLimitError extends Error {},
  fetchScheduledRunEventStream: jest.fn(),
  fetchSession: jest.fn(),
  interruptMessageStream: jest.fn(),
  processSSEStream: jest.fn(),
  sendMessageStream: jest.fn(),
}));

const sessionId = "session-thinking";

describe("useBuildStreaming thinking packets", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    useBuildSessionStore.setState({
      currentSessionId: null,
      sessions: new Map(),
    } as never);
    useBuildSessionStore.getState().createSession(sessionId, {
      status: "active",
      isLoaded: true,
    });

    jest.mocked(sendMessageStream).mockResolvedValue({} as Response);
    jest
      .mocked(processSSEStream)
      .mockImplementation(async (_response, onPacket) => {
        onPacket({
          sessionUpdate: "agent_thought_chunk",
          content: { type: "text", text: "Inspecting the app state." },
          timestamp: "2026-01-01T00:00:00Z",
        } as never);
        onPacket({
          type: "tool_call_start",
          tool_call_id: "tool-read",
          kind: "read",
          title: "Read file",
          content: null,
          locations: null,
          raw_input: null,
          raw_output: null,
          status: "pending",
          timestamp: "2026-01-01T00:00:01Z",
        });
      });
  });

  afterEach(() => {
    act(() => {
      jest.runOnlyPendingTimers();
    });
    jest.useRealTimers();
  });

  it("settles a thought when the next packet arrives while keeping the row visible", async () => {
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamMessage(sessionId, "build the app");
    });

    const streamItems =
      useBuildSessionStore.getState().sessions.get(sessionId)?.streamItems ??
      [];

    expect(streamItems).toHaveLength(2);
    expect(streamItems[0]).toMatchObject({
      type: "thinking",
      content: "Inspecting the app state.",
      isStreaming: false,
    });
    expect(streamItems[1]).toMatchObject({
      type: "tool_call",
      id: "tool-read",
    });
  });

  it("saves thought stream items into assistant metadata on prompt_response", async () => {
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          sessionUpdate: "agent_thought_chunk",
          content: { type: "text", text: "Inspecting the app state." },
          timestamp: "2026-01-01T00:00:00Z",
        } as never);
        onPacket({
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text: "Built the app." },
          timestamp: "2026-01-01T00:00:01Z",
        } as never);
        onPacket({
          type: "prompt_response",
          timestamp: "2026-01-01T00:00:02Z",
        });
      });

    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamMessage(sessionId, "build the app");
    });

    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    const assistantMessage = session?.messages.find(
      (message) => message.type === "assistant"
    );
    const metadata = assistantMessage?.message_metadata as
      | { streamItems?: StreamItem[] }
      | undefined;

    expect(session?.streamItems).toEqual([]);
    expect(assistantMessage?.content).toBe("Built the app.");
    expect(metadata?.streamItems).toEqual([
      expect.objectContaining({
        type: "thinking",
        content: "Inspecting the app state.",
        isStreaming: false,
      }),
      expect.objectContaining({
        type: "text",
        content: "Built the app.",
        isStreaming: false,
      }),
    ]);
  });
});
