import { renderHook, waitFor } from "@testing-library/react";
import { ReadonlyURLSearchParams } from "next/navigation";
import useChatSessionController from "@/hooks/useChatSessionController";
import {
  BackendChatSession,
  BackendMessage,
  ChatSessionSharedStatus,
  Message,
} from "@/app/app/interfaces";
import { Packet } from "@/app/app/services/streamingModels";

const mockUpdateTree = jest.fn();
const mockResume = jest.fn();
const mockState = {
  currentSessionId: "session",
  sessions: new Map<string, { chatState: string }>(),
  updateSessionAndMessageTree: mockUpdateTree,
  updateSessionMessageTree: jest.fn(),
  setIsFetchingChatMessages: jest.fn(),
  setCurrentSession: jest.fn(),
  initializeSession: jest.fn(),
  updateCurrentChatSessionSharedStatus: jest.fn(),
  updateCurrentSelectedNodeForDocDisplay: jest.fn(),
  updateSessionData: jest.fn(),
};
const mockHistory: Message[] = [];
jest.mock("@/app/app/stores/useChatSessionStore", () => ({
  useChatSessionStore: Object.assign(
    (selector: (state: typeof mockState) => unknown) => selector(mockState),
    { getState: () => mockState }
  ),
  useCurrentMessageHistory: () => mockHistory,
}));
jest.mock("@/app/app/services/lib", () => ({
  ...jest.requireActual<typeof import("@/app/app/services/lib")>(
    "@/app/app/services/lib"
  ),
  resumeStream: (sessionId: string, cursor: number, signal: AbortSignal) =>
    mockResume(sessionId, cursor, signal),
}));
jest.mock("@/providers/IncognitoProvider", () => ({
  useIncognito: () => ({
    setIncognitoEnabled: jest.fn(),
    setIncognitoSessionId: jest.fn(),
  }),
}));
jest.mock("@/lib/projects/svc", () => ({
  getSessionProjectTokenCount: async () => 0,
  getProjectFilesForSession: async () => [],
}));

const savedPackets: Packet[] = [
  {
    identity: {
      response_id: 12,
      run_id: "root",
      message_id: "root:0",
      part_id: "answer",
    },
    obj: {
      type: "item_update",
      item: {
        kind: "text",
        purpose: "answer",
        text: "Saved after the persistence wait expired.",
        status: "complete",
        documents: [],
        citations: [],
      },
    },
  },
  { obj: { type: "stop" } },
];

function renderController() {
  return renderHook(() =>
    useChatSessionController({
      existingChatSessionId: "session",
      searchParams: new ReadonlyURLSearchParams(new URLSearchParams()),
      setSelectedDocuments: jest.fn(),
      setCurrentMessageFiles: jest.fn(),
      chatSessionIdRef: { current: "session" },
      loadedIdSessionRef: { current: "session" },
      chatInputBarRef: { current: null },
      isInitialLoad: { current: true },
      submitOnLoadPerformed: { current: false },
      refreshChatSessions: jest.fn(),
      onSubmit: jest.fn(),
    })
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  mockState.currentSessionId = "session";
});
afterEach(() => jest.restoreAllMocks());

test.each(["404", "gap"])(
  "refreshes a late saved outcome after interrupted replay ends with %s",
  async (failure) => {
    jest.spyOn(console, "error").mockImplementation(() => {});
    mockResume.mockImplementation(async function* () {
      if (failure === "404") throw new Error("No resumable run");
      // A cache gap can end replay before its first content packet.
      yield { obj: { type: "chat_heartbeat" } };
    });
    const message: BackendMessage = {
      message_id: 12,
      message_type: "assistant",
      research_type: null,
      parent_message: null,
      latest_child_message: null,
      message: "",
      rephrased_query: null,
      context_docs: null,
      time_sent: "2026-09-17T00:00:00Z",
      overridden_model: "test",
      alternate_assistant_id: null,
      chat_session_id: "session",
      citations: null,
      files: [],
      tool_call: null,
      current_feedback: null,
      sub_questions: [],
      comments: null,
      parentMessageId: null,
      refined_answer_improvement: null,
      is_agentic: null,
      preferred_response_id: null,
      model_display_name: null,
      error: null,
    };
    const session: BackendChatSession = {
      chat_session_id: "session",
      description: "Saved response",
      persona_id: 1,
      persona_name: "Test",
      time_created: "2026-09-17T00:00:00Z",
      time_updated: "2026-09-17T00:00:00Z",
      shared_status: ChatSessionSharedStatus.Private,
      current_temperature_override: null,
      current_reasoning_effort_override: null,
      owner_name: null,
      messages: [message],
      packets: [[]],
      current_run: { run_id: 12, is_running: false },
    };
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify(session)))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ...session,
            current_run: null,
            packets: [savedPackets],
          })
        )
      );
    renderController();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
      const latest: Map<number, Message> = mockUpdateTree.mock.calls.at(-1)![1];
      expect(latest.get(12)?.packets).toEqual(savedPackets);
    });
  }
);
