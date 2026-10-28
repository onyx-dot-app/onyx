import { render, screen, waitFor } from "@tests/setup/test-utils";
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
