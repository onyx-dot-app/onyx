import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, waitFor } from "@testing-library/react-native";

import { postApprovalDecision } from "@/api/chat/approvals";
import { getChatSession, getChatSessionStatus } from "@/api/chat/sessions";
import { resumeChatMessage, type StreamEvent } from "@/api/chat/stream";
import { BackendChatSession } from "@/chat/interfaces";
import { getMessageByMessageId } from "@/chat/messageTree";
import { Packet, PacketType, StopReason } from "@/chat/streamingModels";
import { APPROVAL_CARDS, useToolApprovalUi } from "@/chat/toolApprovals";
import { ToolApprovalCard } from "@/components/chat/ToolApprovalCard";
import { useChatController } from "@/hooks/useChatController";
import { useChatSessionController } from "@/hooks/useChatSessionController";
import { useToolCards } from "@/hooks/useToolCards";
import { useChatSessionStore } from "@/state/chatSessionStore";

jest.mock("expo-router", () => ({
  router: { replace: jest.fn(), navigate: jest.fn() },
}));
jest.mock("@/state/session", () => ({
  useSession: (selector: (s: { serverUrl: string | null }) => unknown) =>
    selector({ serverUrl: "https://example.test" }),
}));
jest.mock("@/hooks/useToast", () => ({
  toast: { info: jest.fn(), error: jest.fn(), warning: jest.fn() },
}));
jest.mock("@/api/chat/approvals", () => ({ postApprovalDecision: jest.fn() }));
jest.mock("@/api/chat/sessions", () => ({
  getChatSession: jest.fn(),
  getChatSessionStatus: jest.fn(),
}));
jest.mock("@/api/chat/stream", () => ({
  streamChatMessage: jest.fn(),
  resumeChatMessage: jest.fn(),
  isHeartbeat: (event: { obj?: { type?: string } }) =>
    event.obj?.type === "chat_heartbeat",
  isPacket: (event: { obj?: unknown; placement?: unknown }) =>
    "obj" in event && "placement" in event,
  isMessageIdInfo: (event: { user_message_id?: unknown }) =>
    "user_message_id" in event,
  isStreamCursor: (event: { next_cursor?: unknown }) => "next_cursor" in event,
  isStreamError: (event: { error?: unknown }) =>
    "error" in event && typeof event.error === "string",
  StreamHttpError: class StreamHttpError extends Error {},
}));
// The pending card's spinner loops forever, which keeps async queries from settling.
jest.mock("@/hooks/useReducedMotion", () => ({ useReducedMotion: () => true }));

const resumeMock = resumeChatMessage as unknown as Mock<
  (
    id: string,
    streamId: number,
    cursor: number,
    signal: AbortSignal,
  ) => AsyncGenerator<StreamEvent>
>;
const postMock = postApprovalDecision as unknown as Mock<
  typeof postApprovalDecision
>;

const request: Packet = {
  placement: { turn_index: 0 },
  obj: {
    type: PacketType.TOOL_APPROVAL_REQUEST,
    approval_id: "a1",
    tool_call_id: "c1",
    tool_name: "lookup",
    display_name: "Lookup",
    arguments: { query: "weather" },
  },
};
const pausedStop: Packet = {
  placement: { turn_index: 0 },
  obj: { type: PacketType.STOP, stop_reason: StopReason.AWAITING_USER },
};

function savedSession(packets: Packet[]): BackendChatSession {
  return {
    chat_session_id: "s1",
    description: "",
    persona_id: 0,
    messages: [
      {
        message_id: 10,
        message_type: "user",
        parent_message: null,
        latest_child_message: 11,
        message: "Question",
        files: [],
        time_sent: "",
        error: null,
      },
      {
        message_id: 11,
        message_type: "assistant",
        parent_message: 10,
        latest_child_message: null,
        message: "",
        files: [],
        time_sent: "",
        error: null,
      },
    ],
    packets: [packets],
    time_created: "",
    // A parked response runs nowhere.
    current_stream: null,
  };
}

const NO_PACKETS: Packet[] = [];

// The chat screen's session hooks with the answer's approval cards.
function OpenChat() {
  const { messages } = useChatController("s1");
  useChatSessionController("s1");
  const approvals = useToolCards(
    messages[1]?.packets ?? NO_PACKETS,
    APPROVAL_CARDS,
  );
  return approvals.map((approval) => (
    <ToolApprovalCard key={approval.request.approval_id} approval={approval} />
  ));
}

describe("a parked session opened from saved history", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useChatSessionStore.setState({
      currentSessionId: null,
      sessions: new Map(),
    });
    useToolApprovalUi.setState({ localStatuses: new Map(), nudgeSeq: 0 });
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValue({ is_processing: false });
  });

  it("shows an actionable card, and approving follows the continuation the server names", async () => {
    const answer: Packet = {
      placement: { turn_index: 1 },
      obj: { type: PacketType.MESSAGE_START, id: "m", content: "Sunny" },
    };
    const resolution: Packet = {
      placement: { turn_index: 0 },
      obj: {
        type: PacketType.TOOL_APPROVAL_RESOLVED,
        approval_id: "a1",
        outcome: "approved",
      },
    };
    const finished: Packet = {
      placement: { turn_index: 1 },
      obj: { type: PacketType.STOP, stop_reason: StopReason.FINISHED },
    };
    jest
      .mocked(getChatSession)
      .mockResolvedValueOnce(savedSession([request, pausedStop]))
      .mockResolvedValue(savedSession([request, resolution, answer, finished]));
    // The continuation's stream ID is no message ID.
    postMock.mockResolvedValue({
      approval_id: "a1",
      decision: "APPROVED",
      decided_via: "USER",
      continuation: { stream_id: 40, response_ids: [11] },
    });
    resumeMock.mockReturnValue(
      (async function* (): AsyncGenerator<StreamEvent> {
        yield request;
        yield resolution;
        yield answer;
        yield finished;
        yield { stream_id: 40, next_cursor: 4, replay_complete: true };
      })(),
    );

    const view = render(
      <QueryClientProvider
        client={
          new QueryClient({
            defaultOptions: { queries: { retry: false, gcTime: 0 } },
          })
        }
      >
        <OpenChat />
      </QueryClientProvider>,
    );

    // The first render loads the card's modules, which is slow under a loaded jest run.
    expect(
      await view.findByText(
        "Approval requested: Lookup",
        {},
        { timeout: 15_000 },
      ),
    ).toBeTruthy();
    expect(useChatSessionStore.getState().sessions.get("s1")?.chatState).toBe(
      "input",
    );
    fireEvent.press(view.getByText("Approve once"));

    await waitFor(() =>
      expect(resumeMock).toHaveBeenCalledWith("s1", 40, 0, expect.anything()),
    );
    expect(postMock).toHaveBeenCalledWith("a1", "approve_once");
    expect(await view.findByText("Approved: Lookup")).toBeTruthy();
    await waitFor(() =>
      expect(useChatSessionStore.getState().sessions.get("s1")?.chatState).toBe(
        "input",
      ),
    );
    const tree = useChatSessionStore.getState().sessions.get("s1")!.messageTree;
    expect(getMessageByMessageId(tree, 11)?.packets).toContainEqual(answer);
    view.unmount();
  }, 20_000);
});
