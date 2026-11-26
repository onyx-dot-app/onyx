import { render, screen } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import type { MinimalAgent } from "@/lib/agents/types";
import type { Message } from "@/app/app/types";
import { PacketType, StopReason } from "@/app/app/services/streamingModels";
import { SubagentTranscript } from "@/sections/chat/SubagentTranscript";

const FILE_ID = "3f2a9c1e-0000-4000-8000-000000000000";

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

const placement = { turn_index: 0, tab_index: 0 };
const answer: Message = {
  nodeId: 2,
  messageId: 2,
  parentNodeId: 1,
  type: "assistant",
  message: "",
  files: [],
  toolCall: null,
  packets: [
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
      obj: {
        type: PacketType.MESSAGE_DELTA,
        content: `See [the report](/api/chat/file/${FILE_ID}).`,
      },
    },
    {
      placement,
      obj: { type: PacketType.STOP, stop_reason: StopReason.FINISHED },
    },
  ],
};

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
jest.mock("@/lib/agents/hooks", () => ({ useActiveAgent: () => agent }));
jest.mock("@/lib/chat/hooks", () => ({
  ...jest.requireActual("@/lib/chat/hooks"),
  useChatSubagents: () => ({
    agents: [],
    loaded: true,
    stopAgent: jest.fn(),
  }),
  useSubagentTranscript: () => ({
    messages: [answer],
    loading: false,
    failed: false,
  }),
}));

test("a cited file in a transcript opens the page's preview", async () => {
  const setPresentingDocument = jest.fn();
  render(
    <SubagentTranscript
      sessionId="chat-1"
      agentId="agent-1"
      setPresentingDocument={setPresentingDocument}
    />
  );

  await userEvent.click(screen.getByRole("button", { name: "the report" }));

  expect(setPresentingDocument).toHaveBeenCalledWith({
    document_id: FILE_ID,
    semantic_identifier: "the report",
  });
});
