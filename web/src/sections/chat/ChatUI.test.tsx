import { act, render, screen, waitFor, within } from "@tests/setup/test-utils";
import ChatUI, { ChatUIProps } from "@/sections/chat/ChatUI";
import { processRawChatHistory } from "@/app/app/services/lib";
import { preserveFailedMessages } from "@/lib/chat/settleChatSession";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import type { BackendMessage, Message } from "@/app/app/types";
import type { Packet } from "@/app/app/services/streamingModels";

jest.mock("@/components/chat/DynamicBottomSpacer", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/providers/VoiceModeProvider", () => ({
  useVoiceMode: () => ({
    resetTTS: jest.fn(),
    streamTTS: jest.fn(),
    stopTTS: jest.fn(),
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
    .setUncaughtError("session", { error: "Could not load this session" });
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

test("readiness errors do not offer regeneration before input is available", () => {
  useChatSessionStore.getState().updateSessionData("session", {
    chatState: "unconfirmed",
    uncaughtError: { error: "Could not confirm readiness" },
  });
  render(<ChatUI {...props} />);
  expect(
    screen.queryByRole("button", { name: /regenerate|retry/i })
  ).not.toBeInTheDocument();
});

test.each([false, true])(
  "accepted instructions remain visible after loading a response (multi-model: %s)",
  async (multiModel) => {
    const restored = processRawChatHistory(
      [saved],
      [
        [
          {
            placement: { turn_index: 0 },
            obj: {
              type: "message_start",
              id: "earlier",
              final_documents: [],
              content: "Earlier answer",
            },
          },
          { placement: { turn_index: 0 }, obj: { type: "section_end" } },
          {
            placement: { turn_index: 1 },
            obj: {
              type: "user_message",
              id: "instruction",
              message: "Use the latest report",
            },
          },
          {
            placement: { turn_index: 2 },
            obj: {
              type: "message_start",
              id: "later",
              final_documents: [],
              content: "Later answer",
            },
          },
          { placement: { turn_index: 2 }, obj: { type: "section_end" } },
          { placement: { turn_index: 0 }, obj: { type: "stop" } },
        ],
      ]
    );
    restored.set(
      1,
      multiModel ? { ...question, childrenNodeIds: [2, 3] } : question
    );
    if (multiModel) {
      restored.set(3, {
        ...failed,
        nodeId: 3,
        messageId: 3,
        modelDisplayName: "Other model",
      });
    }
    useChatSessionStore
      .getState()
      .updateSessionMessageTree("session", restored);
    const view = render(<ChatUI {...props} />);
    expect(
      screen.queryByText("Sent during this response")
    ).not.toBeInTheDocument();
    const input = await screen.findByText("Use the latest report");
    expect(
      screen.getByText("Earlier answer").compareDocumentPosition(input) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      input.compareDocumentPosition(screen.getByText("Later answer")) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(screen.getAllByText("Use the latest report")).toHaveLength(1);
    view.unmount();
    render(<ChatUI {...props} />);
    expect(screen.getAllByText("Use the latest report")).toHaveLength(1);
  }
);

test("accepting an instruction reveals preceding text before its user bubble", () => {
  const animation = jest
    .spyOn(window, "requestAnimationFrame")
    .mockImplementation(() => 1);
  const packets: Packet[] = [
    {
      placement: { turn_index: 0 },
      obj: {
        type: "message_start",
        id: "earlier",
        content: "",
        final_documents: [],
      },
    },
  ];
  const response: Message = {
    ...failed,
    type: "assistant",
    message: "",
    packets,
    packetCount: packets.length,
  };
  const publish = () =>
    useChatSessionStore.getState().updateSessionData("session", {
      chatState: "streaming",
      messageTree: new Map([
        [1, question],
        [2, { ...response, packetCount: packets.length }],
      ]),
    });
  publish();
  const view = render(<ChatUI {...props} />);
  try {
    act(() => {
      packets.push({
        placement: { turn_index: 0 },
        obj: { type: "message_delta", content: "The complete earlier answer" },
      });
      packets.push({
        placement: { turn_index: 0 },
        obj: { type: "section_end" },
      });
      publish();
    });
    expect(
      screen.queryByText("The complete earlier answer")
    ).not.toBeInTheDocument();
    act(() => {
      packets.push({
        placement: { turn_index: 1 },
        obj: {
          type: "user_message",
          id: "instruction",
          message: "Use the latest report",
        },
      });
      publish();
    });
    const input = screen.getByText("Use the latest report");
    expect(
      screen
        .getByText("The complete earlier answer")
        .compareDocumentPosition(input) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  } finally {
    view.unmount();
    animation.mockRestore();
  }
});

test("an automatic follow-up renders a divider instead of a user bubble", () => {
  const answer = (id: string, content: string): Packet[] => [
    {
      placement: { turn_index: 0 },
      obj: { type: "message_start", id, final_documents: [], content },
    },
    { placement: { turn_index: 0 }, obj: { type: "section_end" } },
    { placement: { turn_index: 0 }, obj: { type: "stop" } },
  ];
  const response: BackendMessage = {
    ...saved,
    error: null,
    error_info: null,
  };
  const tree = processRawChatHistory(
    [
      {
        ...response,
        message_id: 1,
        message_type: "user",
        parent_message: null,
        latest_child_message: 2,
        message: "hi",
      },
      { ...response, latest_child_message: 3, message: "Earlier answer" },
      {
        ...response,
        message_id: 3,
        message_type: "agent_results",
        parent_message: 2,
        latest_child_message: 4,
        message: "",
      },
      {
        ...response,
        message_id: 4,
        parent_message: 3,
        message: "Follow-up answer",
      },
    ],
    [
      answer("earlier", "Earlier answer"),
      answer("follow-up", "Follow-up answer"),
    ]
  );
  useChatSessionStore.getState().updateSessionMessageTree("session", tree);
  render(<ChatUI {...props} />);

  const divider = screen.getByText("Subagent results received");
  expect(screen.getAllByTestId("human-message-bubble")).toHaveLength(1);
  expect(
    screen.getByText("Earlier answer").compareDocumentPosition(divider) &
      Node.DOCUMENT_POSITION_FOLLOWING
  ).toBeTruthy();
  expect(
    divider.compareDocumentPosition(screen.getByText("Follow-up answer")) &
      Node.DOCUMENT_POSITION_FOLLOWING
  ).toBeTruthy();
  // The follow-up names its model but has no question to regenerate from.
  expect(screen.getAllByTestId("AgentMessage/regenerate")).toHaveLength(1);
  const followUp = screen
    .getByText("Follow-up answer")
    .closest<HTMLElement>('[data-testid="onyx-ai-message"]');
  if (!followUp) throw new Error("Follow-up answer is missing");
  expect(within(followUp).getByText("test")).toBeVisible();
});
