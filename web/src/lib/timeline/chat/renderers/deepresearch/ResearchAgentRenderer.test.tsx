import { render, screen } from "@tests/setup/test-utils";
import { ResearchAgentRenderer } from "@/lib/timeline/chat/renderers/deepresearch/ResearchAgentRenderer";
import {
  FullChatState,
  RenderType,
} from "@/app/app/message/messageComponents/types";
import {
  PacketType,
  ResearchAgentPacket,
} from "@/app/app/services/streamingModels";
import type { MinimalAgent } from "@/lib/agents/types";

const agent: MinimalAgent = {
  id: 0,
  name: "Deep Research",
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

test("a later report start replaces the text of an earlier one", () => {
  const packets: ResearchAgentPacket[] = [
    {
      placement,
      obj: { type: PacketType.RESEARCH_AGENT_START, research_task: "Task" },
    },
    { placement, obj: { type: PacketType.INTERMEDIATE_REPORT_START } },
    {
      placement,
      obj: { type: PacketType.INTERMEDIATE_REPORT_DELTA, content: "Interim." },
    },
    { placement, obj: { type: PacketType.INTERMEDIATE_REPORT_START } },
    {
      placement,
      obj: {
        type: PacketType.INTERMEDIATE_REPORT_DELTA,
        content: "Child report",
      },
    },
    { placement, obj: { type: PacketType.SECTION_END } },
  ];

  render(
    <ResearchAgentRenderer
      packets={packets}
      nestedCalls={[]}
      state={chatState}
      onComplete={() => {}}
      renderType={RenderType.FULL}
      animate={false}
      stopPacketSeen={true}
    >
      {(results) => (
        <section aria-label="Research output">{results[0]?.content}</section>
      )}
    </ResearchAgentRenderer>
  );

  const output = screen.getByRole("region", { name: "Research output" });
  expect(output).toHaveTextContent("Child report");
  expect(output).not.toHaveTextContent("Interim.");
});
