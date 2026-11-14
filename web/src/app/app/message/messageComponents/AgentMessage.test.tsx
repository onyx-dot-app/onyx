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
import { useToolApprovalUi } from "@/lib/chat/toolApprovals";
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

jest.mock("@/app/app/message/messageComponents/CustomToolAuthCard", () => ({
  __esModule: true,
  default: ({ toolName }: { toolName: string }) => <p>Connect {toolName}</p>,
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
  });
  store.setCurrentSession(SESSION_ID);
}

afterEach(() => {
  useChatSessionStore.setState({ currentSessionId: null, sessions: new Map() });
  jest.useRealTimers();
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

test("a timed out answer explains its deadline without claiming the user stopped it", async () => {
  seedSessionAwaitingAnswer();
  const packets: Packet[] = [
    ...answerPackets.slice(0, -1),
    {
      placement,
      obj: { type: PacketType.STOP, stop_reason: StopReason.TIMED_OUT },
    },
  ];
  render(
    <AgentMessage
      rawPackets={packets}
      chatState={chatState}
      nodeId={NEW_ANSWER_NODE_ID}
      llmManager={null}
      hideFooter
      disableTTS
    />
  );
  expect(
    await screen.findByText(
      "The response stopped because it reached its time limit."
    )
  ).toBeInTheDocument();
  expect(
    screen.queryByText("User has stopped generation")
  ).not.toBeInTheDocument();
});

test("code mode reads as the tool calls it makes", async () => {
  seedSessionAwaitingAnswer();
  const cell = { turn_index: 0, tab_index: 0 };
  const waited = { turn_index: 1, tab_index: 0 };
  const lookup = (at: typeof cell, done: boolean): Packet[] => [
    {
      placement: { ...at, sub_turn_index: 0 },
      obj: {
        type: PacketType.CUSTOM_TOOL_START,
        tool_name: "lookup_orders",
        display_name: "lookup_orders",
      },
    },
    ...(done
      ? ([
          {
            placement: { ...at, sub_turn_index: 0 },
            obj: {
              type: PacketType.CUSTOM_TOOL_DELTA,
              tool_name: "lookup_orders",
              display_name: "lookup_orders",
              response_type: "text",
              data: "3 orders",
            },
          },
          {
            placement: { ...at, sub_turn_index: 0 },
            obj: { type: PacketType.SECTION_END },
          },
        ] as Packet[])
      : []),
  ];
  const answer = { turn_index: 2, tab_index: 0 };
  const packets: Packet[] = [
    {
      placement: cell,
      obj: { type: PacketType.CODE_MODE_START, code: "await lookup_orders()" },
    },
    ...lookup(cell, false),
    {
      placement: cell,
      obj: {
        type: PacketType.CODE_MODE_DELTA,
        stdout: "started\n",
        status: "running",
        cell_id: 1,
        observation: 0,
      },
    },
    { placement: cell, obj: { type: PacketType.SECTION_END } },
    {
      placement: waited,
      obj: {
        type: PacketType.CODE_MODE_START,
        code: "",
        cell_id: 1,
        observation: 1,
      },
    },
    ...lookup(waited, true),
    {
      placement: waited,
      obj: {
        type: PacketType.CODE_MODE_DELTA,
        stdout: "done\n",
        status: "completed",
        cell_id: 1,
        observation: 1,
      },
    },
    { placement: waited, obj: { type: PacketType.SECTION_END } },
    {
      placement: answer,
      obj: {
        type: PacketType.MESSAGE_START,
        id: "answer",
        content: "",
        final_documents: null,
      },
    },
    {
      placement: answer,
      obj: { type: PacketType.MESSAGE_DELTA, content: "You have 3 orders." },
    },
    {
      placement: answer,
      obj: { type: PacketType.STOP, stop_reason: StopReason.FINISHED },
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
    expect(await screen.findByText("You have 3 orders.")).toBeInTheDocument();
    // One cell, observed twice, made one call.
    expect(screen.getByText("1 step")).toBeInTheDocument();
    await act(async () => {
      screen.getByRole("button", { name: "Expand timeline" }).click();
    });
    const timeline = view.container;
    await waitFor(() =>
      expect(screen.getAllByText(/lookup_orders/)).toHaveLength(1)
    );
    expect(timeline).not.toHaveTextContent(
      /Ran code|cell|continues|started|await lookup_orders|Analyz/i
    );
  } finally {
    view.unmount();
  }
});

test("a later report of a code mode call replaces what the step shows", async () => {
  seedSessionAwaitingAnswer();
  const cell = { turn_index: 0, tab_index: 0 };
  const waited = { turn_index: 1, tab_index: 0 };
  const call = { sub_turn_index: 0 };
  const output = (at: typeof cell, data: string): Packet => ({
    placement: { ...at, ...call },
    obj: {
      type: PacketType.CUSTOM_TOOL_DELTA,
      tool_name: "lookup_orders",
      response_type: "text",
      data,
    },
  });
  const start = (at: typeof cell): Packet => ({
    placement: { ...at, ...call },
    obj: {
      type: PacketType.CUSTOM_TOOL_START,
      tool_name: "lookup_orders",
      display_name: "lookup_orders",
    },
  });
  // The call is running when the program yields; the wait_code observation
  // reports it again with as many packets.
  const yielded: Packet[] = [
    { placement: cell, obj: { type: PacketType.CODE_MODE_START, code: "" } },
    start(cell),
    output(cell, "checking"),
    output(cell, "checking more"),
    {
      placement: cell,
      obj: {
        type: PacketType.CODE_MODE_DELTA,
        stdout: "",
        status: "running",
        cell_id: 1,
      },
    },
    { placement: cell, obj: { type: PacketType.SECTION_END } },
  ];
  const completed: Packet[] = [
    ...yielded,
    {
      placement: waited,
      obj: { type: PacketType.CODE_MODE_START, code: "", cell_id: 1 },
    },
    start(waited),
    output(waited, "3 orders"),
    {
      placement: { ...waited, ...call },
      obj: { type: PacketType.SECTION_END },
    },
  ];
  const renderMessage = (packets: Packet[]) => (
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
  const view = render(renderMessage(yielded));
  try {
    await act(async () => {
      (await screen.findByRole("button", { name: "Expand timeline" })).click();
    });
    expect(await screen.findByText("checking more")).toBeInTheDocument();

    view.rerender(renderMessage(completed));
    expect(
      await screen.findByText("lookup_orders completed")
    ).toBeInTheDocument();
    expect(screen.getByText("3 orders")).toBeInTheDocument();
    expect(screen.queryByText("checking more")).not.toBeInTheDocument();
  } finally {
    view.unmount();
  }
});

test("a program call that waits for approval shows the nested tool and a waiting header", async () => {
  seedSessionAwaitingAnswer();
  useToolApprovalUi.setState({ localStatuses: new Map(), nudge: null });
  const cell = { turn_index: 0, tab_index: 0 };
  const nested = { ...cell, sub_turn_index: 0 };
  // The program's call starts, then the request arrives at the cell's placement.
  const packets: Packet[] = [
    {
      placement: cell,
      obj: { type: PacketType.CODE_MODE_START, code: "await create_issue()" },
    },
    {
      placement: nested,
      obj: {
        type: PacketType.CUSTOM_TOOL_START,
        tool_name: "mcp__3__github__create_issue",
        display_name: "Create issue",
      },
    },
    {
      placement: cell,
      obj: {
        type: PacketType.TOOL_APPROVAL_REQUEST,
        approval_id: "approval",
        tool_call_id: "nested-call",
        tool_name: "mcp__3__github__create_issue",
        display_name: "Create issue",
        arguments: { title: "Fix login" },
        expires_at: "2099-01-01T00:00:00Z",
      },
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
    expect(
      await screen.findByRole("button", {
        name: /^Approval requested: Create issue Approve by/,
      })
    ).toBeInTheDocument();
    expect(screen.getByText("Waiting for your approval")).toBeInTheDocument();
    expect(screen.queryByText("Working")).not.toBeInTheDocument();

    // A decision this client made ends the wait before its packet arrives.
    act(() =>
      useToolApprovalUi.setState({
        localStatuses: new Map([["approval", "approved"]]),
      })
    );
    expect(
      screen.queryByText("Waiting for your approval")
    ).not.toBeInTheDocument();

    const resolved: Packet[] = [
      ...packets,
      {
        placement: cell,
        obj: {
          type: PacketType.TOOL_APPROVAL_RESOLVED,
          approval_id: "approval",
          outcome: "approved",
        },
      },
    ];
    view.rerender(
      <AgentMessage
        rawPackets={resolved}
        packetCount={resolved.length}
        chatState={chatState}
        nodeId={NEW_ANSWER_NODE_ID}
        llmManager={null}
        hideFooter
        disableTTS
      />
    );
    expect(
      await screen.findAllByText("Approved: Create issue")
    ).not.toHaveLength(0);
    expect(
      screen.queryByText("Waiting for your approval")
    ).not.toBeInTheDocument();
  } finally {
    view.unmount();
  }
});

test("a running program shows working over a parallel turn", async () => {
  seedSessionAwaitingAnswer();
  const packets: Packet[] = [0, 1].map((tab_index) => ({
    placement: { turn_index: 0, tab_index },
    obj: { type: PacketType.SEARCH_TOOL_START, is_internet_search: false },
  }));
  packets.push({
    placement: { turn_index: 0, tab_index: 2 },
    obj: { type: PacketType.CODE_MODE_START, code: "" },
  });
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
    expect(await screen.findByText("Working")).toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  } finally {
    view.unmount();
  }
});

test("an expanded step keeps its state when a call is inserted before it", async () => {
  seedSessionAwaitingAnswer();
  const cell = { turn_index: 0, tab_index: 0 };
  const call = (
    toolName: string,
    placement: Packet["placement"],
    data: string
  ): Packet[] => [
    {
      placement,
      obj: {
        type: PacketType.CUSTOM_TOOL_START,
        tool_name: toolName,
        display_name: toolName,
      },
    },
    {
      placement,
      obj: {
        type: PacketType.CUSTOM_TOOL_DELTA,
        tool_name: toolName,
        response_type: "text",
        data,
      },
    },
    { placement, obj: { type: PacketType.SECTION_END } },
  ];
  const packets: Packet[] = [
    { placement: cell, obj: { type: PacketType.CODE_MODE_START, code: "" } },
    ...call("lookup_orders", { ...cell, sub_turn_index: 0 }, "3 orders"),
    ...call("weather", { turn_index: 0, tab_index: 1 }, "sunny"),
  ];
  const renderMessage = (packets: Packet[]) => (
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
  const view = render(renderMessage(packets));
  try {
    await act(async () => {
      (await screen.findByRole("button", { name: "Expand timeline" })).click();
    });
    const weather = await screen.findByText("sunny");

    // The new call takes the turn index that the direct step had.
    view.rerender(
      renderMessage([
        ...packets,
        ...call("lookup_refunds", { ...cell, sub_turn_index: 1 }, "1 refund"),
      ])
    );

    expect(await screen.findByText("1 refund")).toBeInTheDocument();
    // The same node: React kept the step and its state, such as expanded.
    expect(screen.getByText("sunny")).toBe(weather);
  } finally {
    view.unmount();
  }
});

test("a program without tool calls shows only a working header", async () => {
  seedSessionAwaitingAnswer();
  const cell = { turn_index: 0, tab_index: 0 };
  const running: Packet[] = [
    {
      placement: cell,
      obj: { type: PacketType.CODE_MODE_START, code: "print(sum(range(9)))" },
    },
    {
      placement: cell,
      obj: { type: PacketType.CODE_MODE_DELTA, stdout: "36\n" },
    },
  ];
  const renderMessage = (packets: Packet[]) => (
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
  const view = render(renderMessage(running));
  try {
    expect(await screen.findByText("Working")).toBeInTheDocument();
    expect(view.container).not.toHaveTextContent(/36|sum\(range|step/i);

    // A finished response is no longer working, even with no final delta.
    view.rerender(
      renderMessage([
        ...running,
        {
          placement: cell,
          obj: { type: PacketType.STOP, stop_reason: StopReason.FINISHED },
        },
      ])
    );
    await waitFor(() =>
      expect(screen.queryByText("Working")).not.toBeInTheDocument()
    );
  } finally {
    view.unmount();
  }
});

test("generated images from earlier tool steps lead the answer once", async () => {
  seedSessionAwaitingAnswer();
  const image = {
    file_id: "generated-1",
    url: "/api/chat/file/generated-1",
    revised_prompt: "An onyx stone",
  };
  const packets: Packet[] = [
    {
      placement: { turn_index: 0 },
      obj: { type: PacketType.IMAGE_GENERATION_TOOL_START },
    },
    {
      placement: { turn_index: 0 },
      obj: {
        type: PacketType.IMAGE_GENERATION_TOOL_DELTA,
        images: [image, image],
      },
    },
    { placement: { turn_index: 0 }, obj: { type: PacketType.SECTION_END } },
    {
      placement: { turn_index: 1 },
      obj: { type: PacketType.SEARCH_TOOL_START },
    },
    { placement: { turn_index: 1 }, obj: { type: PacketType.SECTION_END } },
    ...answerPackets.map((packet) => ({
      ...packet,
      placement: { turn_index: 2 },
    })),
  ];
  const view = render(
    <AgentMessage
      rawPackets={packets}
      chatState={chatState}
      nodeId={NEW_ANSWER_NODE_ID}
      llmManager={null}
      hideFooter
      disableTTS
    />
  );
  try {
    const answer = await screen.findByText("A quick answer.");
    const images = screen.getAllByRole("img", { name: "Chat attachment" });
    expect(images).toHaveLength(1);
    expect(images[0]).toHaveAttribute("src", image.url);
    expect(images[0]?.compareDocumentPosition(answer)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
  } finally {
    view.unmount();
  }
});

function generatedImageStep(turnIndex: number, fileId: string): Packet[] {
  return [
    {
      placement: { turn_index: turnIndex },
      obj: { type: PacketType.IMAGE_GENERATION_TOOL_START },
    },
    {
      placement: { turn_index: turnIndex },
      obj: {
        type: PacketType.IMAGE_GENERATION_TOOL_DELTA,
        images: [
          {
            file_id: fileId,
            url: `/api/chat/file/${fileId}`,
            revised_prompt: "An onyx stone",
          },
        ],
      },
    },
    {
      placement: { turn_index: turnIndex },
      obj: { type: PacketType.SECTION_END },
    },
  ];
}

test.each([
  {
    scenario: "cancellation without answer text",
    cancelled: true,
    repeated: false,
  },
  {
    scenario: "a second image generation step",
    cancelled: false,
    repeated: false,
  },
  {
    scenario: "the same image in a later generation step",
    cancelled: false,
    repeated: true,
  },
])(
  "retains generated images after $scenario",
  async ({ cancelled, repeated }) => {
    seedSessionAwaitingAnswer();
    const initialPackets = generatedImageStep(0, "first-image");
    const renderMessage = (packets: Packet[]) => (
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
    const view = render(renderMessage(initialPackets));
    try {
      expect(
        await screen.findByRole("img", { name: "Chat attachment" })
      ).toHaveAttribute("src", "/api/chat/file/first-image");
      const finalPackets: Packet[] = cancelled
        ? [
            ...initialPackets,
            {
              placement: { turn_index: 1 },
              obj: {
                type: PacketType.STOP,
                stop_reason: StopReason.USER_CANCELLED,
              },
            },
          ]
        : [
            ...initialPackets,
            ...generatedImageStep(1, repeated ? "first-image" : "second-image"),
            ...answerPackets.map((packet) => ({
              ...packet,
              placement: { turn_index: 2 },
            })),
          ];
      view.rerender(renderMessage(finalPackets));
      const images = await screen.findAllByRole("img", {
        name: "Chat attachment",
      });
      expect(images).toHaveLength(cancelled || repeated ? 1 : 2);
      expect(images[0]).toHaveAttribute("src", "/api/chat/file/first-image");
      if (cancelled) {
        expect(screen.queryByText("A quick answer.")).not.toBeInTheDocument();
      } else {
        if (!repeated) {
          expect(images[1]).toHaveAttribute(
            "src",
            "/api/chat/file/second-image"
          );
        }
        const answer = await screen.findByText("A quick answer.");
        for (const image of images) {
          expect(image.compareDocumentPosition(answer)).toBe(
            Node.DOCUMENT_POSITION_FOLLOWING
          );
        }
      }
    } finally {
      view.unmount();
    }
  }
);

test("generated images remain visible when another tool follows answer text", async () => {
  seedSessionAwaitingAnswer();
  const initialPackets = generatedImageStep(0, "retained-image");
  const renderMessage = (packets: Packet[]) => (
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
  const view = render(renderMessage(initialPackets));
  try {
    const image = await screen.findByRole("img", { name: "Chat attachment" });
    const withAnswer = [
      ...initialPackets,
      ...answerPackets.slice(0, 2).map((packet) => ({
        ...packet,
        placement: { turn_index: 1 },
      })),
    ];
    view.rerender(renderMessage(withAnswer));
    await screen.findByText("A quick answer.");
    expect(image).toBeVisible();

    const withLaterTool: Packet[] = [
      ...withAnswer,
      {
        placement: { turn_index: 2 },
        obj: { type: PacketType.SEARCH_TOOL_START },
      },
    ];
    view.rerender(renderMessage(withLaterTool));
    await waitFor(() => {
      expect(screen.getAllByRole("img", { name: "Chat attachment" })).toEqual([
        image,
      ]);
      expect(image).toBeVisible();
    });
  } finally {
    view.unmount();
  }
});

test("a research step shows each of its nested calls once", async () => {
  seedSessionAwaitingAnswer();
  const research = { turn_index: 0, tab_index: 0 };
  const call = (subTurnIndex: number) => ({
    ...research,
    sub_turn_index: subTurnIndex,
  });
  const packets: Packet[] = [
    {
      placement: research,
      obj: {
        type: PacketType.RESEARCH_AGENT_START,
        research_task: "Compare vendor pricing",
      },
    },
    {
      placement: call(1),
      obj: { type: PacketType.SEARCH_TOOL_START, is_internet_search: false },
    },
    {
      placement: call(0),
      obj: { type: PacketType.SEARCH_TOOL_START, is_internet_search: false },
    },
    {
      placement: call(0),
      obj: {
        type: PacketType.SEARCH_TOOL_QUERIES_DELTA,
        queries: ["first query"],
      },
    },
    {
      placement: call(1),
      obj: {
        type: PacketType.SEARCH_TOOL_QUERIES_DELTA,
        queries: ["second query"],
      },
    },
    { placement: call(0), obj: { type: PacketType.SECTION_END } },
    { placement: call(1), obj: { type: PacketType.SECTION_END } },
    { placement: research, obj: { type: PacketType.SECTION_END } },
    {
      placement: { turn_index: 1, tab_index: 0 },
      obj: {
        type: PacketType.MESSAGE_START,
        id: "answer",
        content: "",
        final_documents: null,
      },
    },
    {
      placement: { turn_index: 1, tab_index: 0 },
      obj: { type: PacketType.MESSAGE_DELTA, content: "Done." },
    },
    {
      placement: { turn_index: 1, tab_index: 0 },
      obj: { type: PacketType.STOP, stop_reason: StopReason.FINISHED },
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
    await act(async () => {
      (await screen.findByRole("button", { name: "Expand timeline" })).click();
    });
    expect(await screen.findByText("Compare vendor pricing")).toBeVisible();
    const first = screen.getAllByText("first query");
    const second = screen.getAllByText("second query");
    expect(first).toHaveLength(1);
    expect(second).toHaveLength(1);
    expect(
      first[0]!.compareDocumentPosition(second[0]!) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  } finally {
    view.unmount();
  }
});

test("a tool step after an accepted user message follows that message", async () => {
  seedSessionAwaitingAnswer();
  const search = (turn_index: number, query: string): Packet[] => [
    {
      placement: { turn_index, tab_index: 0 },
      obj: { type: "search_tool_start", is_internet_search: false },
    },
    {
      placement: { turn_index, tab_index: 0 },
      obj: { type: "search_tool_queries_delta", queries: [query] },
    },
    { placement: { turn_index, tab_index: 0 }, obj: { type: "section_end" } },
  ];
  const packets: Packet[] = [
    ...search(0, "first query"),
    {
      placement: { turn_index: 1, tab_index: 0 },
      obj: {
        type: PacketType.USER_MESSAGE,
        id: "accepted",
        message: "Use the latest report",
      },
    },
    ...search(2, "second query"),
    ...answerPackets.map((packet) => ({
      ...packet,
      placement: { turn_index: 3, tab_index: 0 },
    })),
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
    const bubble = await screen.findByText("Use the latest report");
    // Each search gets its own timeline, on its side of the user message.
    expect(screen.queryByText("2 steps")).not.toBeInTheDocument();
    const timelines = screen.getAllByRole("button", {
      name: "Toggle timeline",
    });
    expect(timelines).toHaveLength(2);
    expect(
      timelines[0]!.compareDocumentPosition(bubble) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      bubble.compareDocumentPosition(timelines[1]!) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  } finally {
    view.unmount();
  }
});

test("an auth error after an accepted user message shows its card without an answer", async () => {
  seedSessionAwaitingAnswer();
  const authError = (turn_index: number): Packet[] => [
    {
      placement: { turn_index, tab_index: 0 },
      obj: {
        type: PacketType.CUSTOM_TOOL_START,
        tool_name: "custom__7__get_user",
        display_name: "Get user",
        tool_id: 7,
      },
    },
    {
      placement: { turn_index, tab_index: 0 },
      obj: {
        type: PacketType.CUSTOM_TOOL_DELTA,
        tool_name: "custom__7__get_user",
        tool_id: 7,
        response_type: "text",
        error: {
          is_auth_error: true,
          is_unreachable: false,
          status_code: 401,
          message: "unauthorized",
        },
      },
    },
  ];
  const packets: Packet[] = [
    ...answerPackets.slice(0, 2),
    ...authError(1),
    {
      placement: { turn_index: 2, tab_index: 0 },
      obj: {
        type: PacketType.USER_MESSAGE,
        id: "accepted",
        message: "Try again",
      },
    },
    ...authError(3),
    {
      placement: { turn_index: 3, tab_index: 0 },
      obj: { type: PacketType.STOP, stop_reason: StopReason.FINISHED },
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
    const bubble = await screen.findByText("Try again");
    const cards = await screen.findAllByText("Connect Get user");
    expect(cards).toHaveLength(2);
    expect(
      bubble.compareDocumentPosition(cards[1]!) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  } finally {
    view.unmount();
  }
});
