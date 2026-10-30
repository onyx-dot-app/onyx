import { act, render, screen, waitFor, within } from "@tests/setup/test-utils";
import { Message } from "@/app/app/types";
import { upsertMessages } from "@/app/app/services/messageTree";
import {
  Packet,
  PacketType,
  StopReason,
} from "@/app/app/services/streamingModels";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import AgentMessage from "@/app/app/message/messageComponents/AgentMessage";
import { FullChatState } from "@/app/app/message/messageComponents/types";
import type { MinimalAgent } from "@/lib/agents/types";

const mockStreamTTS = jest.fn();
const mockStopTTS = jest.fn();

jest.mock("@/providers/VoiceModeProvider", () => ({
  useVoiceMode: () => ({
    resetTTS: jest.fn(),
    streamTTS: mockStreamTTS,
    stopTTS: mockStopTTS,
    revealedCharCount: 0,
    autoPlayback: false,
    isAudioSyncActive: false,
    activeMessageNodeId: null,
    isAwaitingAutoPlaybackStart: false,
  }),
}));

const SESSION_ID = "session-1";
const USER_NODE_ID = 1;
const OLD_ANSWER_NODE_ID = 2;
const NEW_USER_NODE_ID = 3;
const NEW_ANSWER_NODE_ID = 4;

const agent: MinimalAgent = {
  id: 0,
  name: "Default Chat",
  description: "",
  tools: [],
  starter_messages: null,
  document_sets: [],
  is_public: true,
  is_listed: true,
  display_priority: null,
  is_featured: false,
  builtin_persona: true,
  owner: null,
  owner_group: null,
  user_permission: "VIEWER",
};

const chatState: FullChatState = { agent };

const placement = { turn_index: 0, tab_index: 0 };
const answerPackets: Packet[] = [
  {
    placement,
    obj: {
      type: PacketType.MESSAGE_START,
      id: "answer",
      content: "",
      final_documents: null,
    },
  },
  {
    placement,
    obj: { type: PacketType.MESSAGE_DELTA, content: "A quick answer." },
  },
  {
    placement,
    obj: { type: PacketType.STOP, stop_reason: StopReason.FINISHED },
  },
];

function message(
  nodeId: number,
  parentNodeId: number | null,
  type: Message["type"]
): Message {
  return {
    nodeId,
    parentNodeId,
    type,
    message: "",
    files: [],
    toolCall: null,
    packets: [],
  };
}

// A session that just sent a follow-up: the gate is closed and the new
// answer is the latest node.
function seedSessionAwaitingAnswer() {
  const messageTree = upsertMessages(
    new Map(),
    [
      message(USER_NODE_ID, null, "user"),
      message(OLD_ANSWER_NODE_ID, USER_NODE_ID, "assistant"),
      message(NEW_USER_NODE_ID, OLD_ANSWER_NODE_ID, "user"),
      message(NEW_ANSWER_NODE_ID, NEW_USER_NODE_ID, "assistant"),
    ],
    true
  );
  const store = useChatSessionStore.getState();
  store.createSession(SESSION_ID, {
    messageTree,
    chatState: "input",
    latestMessageRenderComplete: false,
  });
  store.setCurrentSession(SESSION_ID);
}

function renderAnswer(messageNodeId: number): void {
  render(
    <AgentMessage
      rawPackets={answerPackets}
      chatState={chatState}
      nodeId={messageNodeId}
      llmManager={null}
      hideFooter
      disableTTS
    />
  );
}

function renderComplete(): boolean | undefined {
  return useChatSessionStore.getState().sessions.get(SESSION_ID)
    ?.latestMessageRenderComplete;
}

describe("AgentMessage queue gate", () => {
  beforeEach(() => {
    seedSessionAwaitingAnswer();
  });

  afterEach(() => {
    useChatSessionStore.setState({
      currentSessionId: null,
      sessions: new Map(),
    });
  });

  test("releases the gate when the latest answer arrives complete", async () => {
    // The whole stream, stop packet included, landed before the first
    // render, so the renderer mounts with animate=false.
    renderAnswer(NEW_ANSWER_NODE_ID);

    expect(await screen.findByText("A quick answer.")).toBeInTheDocument();
    await waitFor(() => expect(renderComplete()).toBe(true));
  });

  test("keeps the gate closed when an older answer mounts", async () => {
    renderAnswer(OLD_ANSWER_NODE_ID);

    expect(await screen.findByText("A quick answer.")).toBeInTheDocument();
    expect(renderComplete()).toBe(false);
  });
});

test("parallel search tabs complete independently", async () => {
  seedSessionAwaitingAnswer();
  const packets: Packet[] = [
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "search_tool_start", is_internet_search: false },
    },
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "search_tool_queries_delta", queries: ["company policy"] },
    },
    {
      placement: { turn_index: 0, tab_index: 1 },
      obj: { type: "search_tool_start", is_internet_search: true },
    },
    {
      placement: { turn_index: 0, tab_index: 1 },
      obj: { type: "search_tool_queries_delta", queries: ["public policy"] },
    },
  ];
  const view = render(
    <AgentMessage
      rawPackets={packets}
      packetCount={packets.length}
      chatState={chatState}
      nodeId={NEW_ANSWER_NODE_ID}
      llmManager={null}
      hideFooter
      disableTTS
    />
  );
  try {
    const internalTab = await screen.findByRole("tab", {
      name: /Internal Search/,
    });
    const webTab = await screen.findByRole("tab", { name: /Web Search/ });
    expect(
      within(internalTab).getByRole("status", { name: "Loading" })
    ).toBeInTheDocument();
    expect(
      within(webTab).getByRole("status", { name: "Loading" })
    ).toBeInTheDocument();
    const completedWeb: Packet[] = [
      ...packets,
      {
        placement: { turn_index: 0, tab_index: 1 },
        obj: { type: "section_end" },
      },
    ];
    view.rerender(
      <AgentMessage
        rawPackets={completedWeb}
        packetCount={completedWeb.length}
        chatState={chatState}
        nodeId={NEW_ANSWER_NODE_ID}
        llmManager={null}
        hideFooter
        disableTTS
      />
    );
    await waitFor(() => {
      expect(
        within(screen.getByRole("tab", { name: /Web Search/ })).queryByRole(
          "status"
        )
      ).not.toBeInTheDocument();
      expect(
        within(screen.getByRole("tab", { name: /Internal Search/ })).getByRole(
          "status",
          { name: "Loading" }
        )
      ).toBeInTheDocument();
    });
  } finally {
    view.unmount();
    useChatSessionStore.setState({
      currentSessionId: null,
      sessions: new Map(),
    });
  }
});

test.each([undefined, 0])(
  "restored output appears immediately and only unfinished tools remain loading (tab: %s)",
  (tabIndex) => {
    seedSessionAwaitingAnswer();
    const placement = { turn_index: 0, tab_index: tabIndex };
    const packets: Packet[] = [
      {
        placement,
        obj: { type: "search_tool_start", is_internet_search: false },
      },
      {
        placement,
        obj: { type: "search_tool_queries_delta", queries: ["internal"] },
      },
      {
        placement: { turn_index: 0, tab_index: 1 },
        obj: { type: "search_tool_start", is_internet_search: true },
      },
      {
        placement: { turn_index: 0, tab_index: 1 },
        obj: { type: "search_tool_queries_delta", queries: ["web"] },
      },
      {
        placement: { turn_index: 0, tab_index: 1 },
        obj: { type: "section_end" },
      },
    ];
    const view = render(
      <AgentMessage
        rawPackets={packets}
        packetCount={packets.length}
        restoredPacketCount={packets.length}
        chatState={chatState}
        nodeId={NEW_ANSWER_NODE_ID}
        llmManager={null}
        hideFooter
        disableTTS
      />
    );
    try {
      expect(
        within(screen.getByRole("tab", { name: /Internal Search/ })).getByRole(
          "status",
          { name: "Loading" }
        )
      ).toBeInTheDocument();
      expect(
        within(screen.getByRole("tab", { name: /Web Search/ })).queryByRole(
          "status"
        )
      ).not.toBeInTheDocument();
      const withAnswer: Packet[] = [
        ...packets,
        {
          placement: { turn_index: 1, tab_index: tabIndex },
          obj: {
            type: "message_start",
            id: "answer",
            content: "Restored answer is already visible.",
            final_documents: null,
          },
        },
      ];
      view.rerender(
        <AgentMessage
          rawPackets={withAnswer}
          packetCount={withAnswer.length}
          restoredPacketCount={withAnswer.length}
          chatState={chatState}
          nodeId={NEW_ANSWER_NODE_ID}
          llmManager={null}
          hideFooter
          disableTTS
        />
      );
      expect(
        screen.getByText("Restored answer is already visible.")
      ).toBeInTheDocument();
      expect(screen.queryByTestId("onyx-ai-message")).not.toBeInTheDocument();
    } finally {
      view.unmount();
    }
  }
);

test.each([0, 1])(
  "live text remains animated after a restored prefix of %s packets",
  (restoredCount) => {
    jest.useFakeTimers();
    seedSessionAwaitingAnswer();
    const packets: Packet[] = [
      {
        placement,
        obj: {
          type: "message_start",
          id: "answer",
          content: restoredCount ? "Saved answer. " : "",
          final_documents: null,
        },
      },
    ];
    const props = {
      chatState,
      nodeId: NEW_ANSWER_NODE_ID,
      llmManager: null,
      hideFooter: true,
      disableTTS: true,
      restoredPacketCount: restoredCount,
    };
    const view = render(
      <AgentMessage
        {...props}
        rawPackets={packets}
        packetCount={packets.length}
      />
    );
    try {
      for (let index = 0; index < 3; index++) {
        packets.push({
          placement,
          obj: {
            type: "message_delta",
            content: "New streaming words continue to appear smoothly. ",
          },
        });
        const previous = view.container.textContent ?? "";
        view.rerender(
          <AgentMessage
            {...props}
            rawPackets={packets}
            packetCount={packets.length}
          />
        );
        act(() => {
          jest.advanceTimersByTime(32);
        });
        const firstFrame = view.container.textContent ?? "";
        expect(firstFrame.length).toBeGreaterThan(previous.length);
        expect(firstFrame).not.toContain(
          "New streaming words continue to appear smoothly. "
            .repeat(index + 1)
            .trim()
        );
        act(() => {
          jest.advanceTimersByTime(32);
        });
        expect((view.container.textContent ?? "").length).toBeGreaterThan(
          firstFrame.length
        );
      }
    } finally {
      view.unmount();
      jest.useRealTimers();
    }
  }
);

test("a failed streaming answer stops its existing autoplay session", async () => {
  mockStreamTTS.mockClear();
  mockStopTTS.mockClear();
  const props = {
    nodeId: 102,
    chatState,
    parentMessage: message(101, null, "user"),
    llmManager: null,
    hideFooter: true,
    packetCount: 1,
    rawPackets: answerPackets.slice(0, 1),
  };
  const view = render(<AgentMessage {...props} />);
  view.rerender(
    <AgentMessage
      {...props}
      rawPackets={answerPackets.slice(0, 2)}
      packetCount={2}
    />
  );
  await waitFor(() => expect(mockStreamTTS).toHaveBeenCalled());
  view.rerender(
    <AgentMessage
      {...props}
      rawPackets={answerPackets.slice(0, 2)}
      packetCount={2}
      disableTTS
    />
  );
  expect(mockStopTTS).toHaveBeenCalledTimes(1);
});
