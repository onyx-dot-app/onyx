import { act, render, screen, waitFor } from "@tests/setup/test-utils";
import ChatUI, { ChatUIProps } from "@/sections/chat/ChatUI";
import { processRawChatHistory } from "@/app/app/services/lib";
import { preserveFailedMessages } from "@/lib/chat/settleChatSession";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import type { BackendMessage, Message } from "@/app/app/types";
import type { Packet } from "@/app/app/services/streamingModels";

jest.mock("@/app/app/message/HumanMessage", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/components/chat/DynamicBottomSpacer", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/providers/VoiceModeProvider", () => ({
  useVoiceMode: () => ({
    resetTTS: jest.fn(),
    revealedCharCount: 0,
    autoPlayback: false,
    isAudioSyncActive: false,
    activeMessageNodeId: null,
    isAwaitingAutoPlaybackStart: false,
  }),
}));

const props: ChatUIProps = {
  activeAgent: {
    id: 0,
    name: "Assistant",
    description: "",
    tools: [],
    starter_messages: null,
    document_sets: [],
    is_public: true,
    is_listed: true,
    display_priority: null,
    is_featured: false,
    builtin_persona: false,
    owner: null,
    owner_group: null,
    user_permission: null,
  },
  llmManager: {
    currentLlm: { name: "provider", provider: "openai", modelName: "test" },
    updateCurrentLlm: jest.fn(),
    temperature: 0,
    updateTemperature: jest.fn(),
    temperatureExplicitlySet: false,
    reasoningEffort: null,
    updateReasoningEffort: jest.fn(),
    hasBoundSession: true,
    persistOverrides: jest.fn(async () => {}),
    updateModelOverrideBasedOnChatSession: jest.fn(),
    imageFilesPresent: false,
    updateImageFilesPresent: jest.fn(),
    activeAgent: null,
    maxTemperature: 2,
    hasTemperatureOverride: false,
    llmProviders: [],
    modelPaging: {
      hasMore: false,
      isLoading: false,
      loadMore: jest.fn(async () => false),
      search: jest.fn(async () => false),
      searchHasMore: false,
      loadMoreSearch: jest.fn(async () => {}),
    },
    isLoadingProviders: false,
    hasAnyProvider: false,
  },
  setPresentingDocument: jest.fn(),
  onMessageSelection: jest.fn(),
  stopGenerating: jest.fn(),
  onSubmit: jest.fn(async () => {}),
  deepResearchEnabled: true,
  currentMessageFiles: [],
  onResubmit: jest.fn(),
};

const question: Message = {
  nodeId: 1,
  messageId: 1,
  type: "user",
  message: "hi",
  files: [],
  toolCall: null,
  packets: [],
  parentNodeId: null,
  childrenNodeIds: [2],
  latestChildNodeId: 2,
};
const failed: Message = {
  nodeId: 2,
  messageId: 2,
  type: "error",
  message: "Partial answer",
  errorMessage: "Provider declined the request",
  errorCode: "MODEL_REFUSAL",
  isRetryable: false,
  files: [],
  toolCall: null,
  parentNodeId: 1,
  packets: [
    {
      placement: { turn_index: 0 },
      obj: {
        type: "message_start",
        id: "answer",
        content: "",
        final_documents: null,
      },
    },
    {
      placement: { turn_index: 0 },
      obj: { type: "message_delta", content: "Partial answer" },
    },
    { placement: { turn_index: 0 }, obj: { type: "stop" } },
  ],
};
const saved: BackendMessage = {
  message_id: 2,
  message_type: "assistant",
  research_type: null,
  parent_message: 1,
  latest_child_message: null,
  message: "Partial answer",
  rephrased_query: null,
  context_docs: null,
  time_sent: "2026-10-27T00:00:00Z",
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
  model_display_name: "Test model",
  error: "Provider declined the request",
  error_info: {
    error: "Provider declined the request",
    error_code: "MODEL_REFUSAL",
    is_retryable: false,
    stack_trace: "",
  },
};

beforeEach(() => {
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: null });
  const store = useChatSessionStore.getState();
  store.createSession("session", {
    chatState: "input",
    messageTree: new Map([
      [1, question],
      [2, failed],
    ]),
  });
  store.setCurrentSession("session");
});

test.each([true, false])(
  "a single-model failure survives refetch and reload (structured: %s)",
  (structured) => {
    const view = render(<ChatUI {...props} />);
    expect(screen.getAllByText("Provider declined the request")).toHaveLength(
      1
    );
    const restored = processRawChatHistory(
      [{ ...saved, error_info: structured ? saved.error_info : undefined }],
      [failed.packets]
    );
    restored.set(1, question);
    const local = useChatSessionStore
      .getState()
      .sessions.get("session")!.messageTree;
    act(() =>
      useChatSessionStore.getState().updateSessionData("session", {
        messageTree: preserveFailedMessages(restored, local),
      })
    );
    expect(screen.getAllByText("Provider declined the request")).toHaveLength(
      1
    );
    expect(screen.getByText("Partial answer")).toBeInTheDocument();
    if (structured)
      expect(
        screen.queryByRole("button", { name: /retry/i })
      ).not.toBeInTheDocument();
    view.unmount();
    render(<ChatUI {...props} />);
    expect(screen.getAllByText("Provider declined the request")).toHaveLength(
      1
    );
  }
);

test("multi-model panels render a failed response once with its partial output", () => {
  const second = {
    ...failed,
    nodeId: 3,
    messageId: 3,
    modelDisplayName: "Other model",
    errorMessage: "Other failure",
  };
  useChatSessionStore.getState().updateSessionData("session", {
    messageTree: new Map([
      [1, { ...question, childrenNodeIds: [2, 3], latestChildNodeId: 3 }],
      [2, { ...failed, modelDisplayName: "Test model" }],
      [3, second],
    ]),
  });
  render(<ChatUI {...props} />);
  expect(screen.getAllByText("Provider declined the request")).toHaveLength(1);
  expect(screen.getAllByText("Other failure")).toHaveLength(1);
  expect(screen.getAllByText("Partial answer")).toHaveLength(2);
});

test("an earlier response error remains visible after another question", () => {
  useChatSessionStore.getState().updateSessionData("session", {
    messageTree: new Map([
      [1, question],
      [2, { ...failed, latestChildNodeId: 3, childrenNodeIds: [3] }],
      [
        3,
        {
          ...question,
          nodeId: 3,
          messageId: 3,
          parentNodeId: 2,
          latestChildNodeId: null,
          childrenNodeIds: [],
        },
      ],
    ]),
  });
  render(<ChatUI {...props} />);
  expect(screen.getByText("Provider declined the request")).toBeInTheDocument();
});

test("a session-load failure is visible alongside an existing response error", () => {
  useChatSessionStore
    .getState()
    .setUncaughtError("session", "Could not load this session");
  render(<ChatUI {...props} />);
  expect(screen.getByText("Provider declined the request")).toBeInTheDocument();
  expect(screen.getByText("Could not load this session")).toBeInTheDocument();
});

test("a failed response keeps partial text and ends search activity", async () => {
  const packets: Packet[] = [
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "search_tool_start", is_internet_search: false },
    },
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "search_tool_queries_delta", queries: ["company policy"] },
    },
  ];
  const streaming: Message = {
    ...failed,
    type: "assistant",
    errorMessage: undefined,
    is_generating: true,
    packets,
    packetCount: packets.length,
  };
  useChatSessionStore.getState().updateSessionData("session", {
    chatState: "streaming",
    messageTree: new Map([
      [1, question],
      [2, streaming],
    ]),
  });
  render(<ChatUI {...props} />);
  expect(
    await screen.findByText("Searching internal documents")
  ).toBeInTheDocument();

  const finishedPackets: Packet[] = [
    ...packets,
    ...failed.packets.map((packet) => ({
      ...packet,
      placement: { turn_index: 1 },
    })),
  ];
  act(() =>
    useChatSessionStore.getState().updateSessionData("session", {
      messageTree: new Map([
        [1, question],
        [
          2,
          {
            ...failed,
            is_generating: false,
            packets: finishedPackets,
            packetCount: finishedPackets.length,
          },
        ],
      ]),
    })
  );
  expect(
    await screen.findByText("Provider declined the request")
  ).toBeInTheDocument();
  expect(await screen.findByText("Partial answer")).toBeInTheDocument();
  await waitFor(() => {
    expect(
      screen.queryByText("Searching internal documents")
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("onyx-ai-message")).toBeInTheDocument();
  });
});
