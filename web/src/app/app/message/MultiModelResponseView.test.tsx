import { act, render } from "@tests/setup/test-utils";
import MultiModelResponseView from "@/app/app/message/MultiModelResponseView";
import type { MultiModelPanelProps } from "@/app/app/message/MultiModelPanel";
import type { MultiModelResponse } from "@/app/app/message/types";
import type { FullChatState } from "@/app/app/message/messageComponents/types";
import type { Message } from "@/app/app/types";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";

const mockPanels = new Map<number, MultiModelPanelProps>();
jest.mock("@/app/app/message/MultiModelPanel", () => ({
  __esModule: true,
  default: (props: MultiModelPanelProps) => {
    mockPanels.set(props.agentMessageProps.nodeId, props);
    return null;
  },
}));
jest.mock("@/app/app/services/lib", () => ({
  setPreferredResponse: jest.fn(),
}));

const chatState: FullChatState = {
  agent: {
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
};

const parent: Message = {
  nodeId: 10,
  type: "user",
  message: "Question",
  files: [],
  toolCall: null,
  packets: [],
  parentNodeId: null,
  childrenNodeIds: [1, 2, 3],
  latestChildNodeId: 3,
};
const responses: MultiModelResponse[] = [1, 2, 3].map((nodeId) => ({
  nodeId,
  modelIndex: nodeId - 1,
  provider: "openai",
  modelName: `model-${nodeId}`,
  displayName: `Model ${nodeId}`,
  packets: [],
  packetCount: 0,
  isGenerating: false,
  errorMessage: nodeId === 3 ? "Provider failed" : null,
}));

beforeEach(() => {
  mockPanels.clear();
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: null });
  const store = useChatSessionStore.getState();
  store.createSession("session", {
    chatState: "input",
    latestMessageRenderComplete: false,
    messageTree: new Map([
      [10, parent],
      ...responses.map((response): [number, Message] => [
        response.nodeId,
        {
          ...parent,
          nodeId: response.nodeId,
          parentNodeId: 10,
          childrenNodeIds: [],
          latestChildNodeId: null,
          type: response.errorMessage ? "error" : "assistant",
        },
      ]),
    ]),
  });
  store.setCurrentSession("session");
});

test("a failed last model does not block the queue once successful panels finish", () => {
  render(
    <MultiModelResponseView
      responses={responses}
      chatState={chatState}
      llmManager={null}
      parentMessage={parent}
    />
  );
  act(() => mockPanels.get(1)!.agentMessageProps.onComplete!(1));
  expect(
    useChatSessionStore.getState().sessions.get("session")!
      .latestMessageRenderComplete
  ).toBe(false);
  act(() => mockPanels.get(2)!.agentMessageProps.onComplete!(2));
  expect(
    useChatSessionStore.getState().sessions.get("session")!
      .latestMessageRenderComplete
  ).toBe(true);
});

test("hidden panels do not wait for an unmounted renderer", () => {
  render(
    <MultiModelResponseView
      responses={responses}
      chatState={chatState}
      llmManager={null}
      parentMessage={parent}
    />
  );
  act(() => mockPanels.get(1)!.agentMessageProps.onComplete!(1));
  act(() => mockPanels.get(2)!.onToggleVisibility());
  expect(
    useChatSessionStore.getState().sessions.get("session")!
      .latestMessageRenderComplete
  ).toBe(true);
});

test.each([10, 20])(
  "old panels cannot release a new response under parent %s",
  (parentNodeId) => {
    render(
      <MultiModelResponseView
        responses={responses}
        chatState={chatState}
        llmManager={null}
        parentMessage={parent}
      />
    );
    const store = useChatSessionStore.getState();
    store.updateSessionMessageTree(
      "session",
      new Map([
        [
          parentNodeId,
          { ...parent, nodeId: parentNodeId, latestChildNodeId: 21 },
        ],
        [
          21,
          {
            ...parent,
            nodeId: 21,
            parentNodeId,
            type: "assistant",
            latestChildNodeId: null,
          },
        ],
      ])
    );
    act(() => {
      mockPanels.get(1)!.agentMessageProps.onComplete!(1);
      mockPanels.get(2)!.agentMessageProps.onComplete!(2);
    });
    expect(
      useChatSessionStore.getState().sessions.get("session")!
        .latestMessageRenderComplete
    ).toBe(false);
  }
);
