import { act, render, screen } from "@tests/setup/test-utils";
import { toPlainString } from "@opal/components/text/InlineMarkdown";
import {
  type CustomToolPacket,
  PacketType,
} from "@/app/app/services/streamingModels";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import type { ChatSessionStatus, ChatSubagent } from "@/lib/chat/types";
import { RenderType } from "@/lib/timeline/chat/message/messageComponents/types";
import { findRenderer } from "@/lib/timeline/chat/message/messageComponents/renderMessageComponent";
import {
  groupSpawnSteps,
  type TransformedStep,
} from "@/lib/timeline/chat/transformers";
import AgentGroupRenderer from "@/lib/timeline/chat/renderers/agent/AgentGroupRenderer";
import { agentToolCalls } from "@/lib/timeline/chat/renderers/agent/agentTools";
import { AgentToolRenderer } from "@/lib/timeline/chat/renderers/agent/AgentToolRenderer";

function spawn(
  tab: number,
  name: string,
  task: string,
  turn = 1
): CustomToolPacket[] {
  const placement = { turn_index: turn, tab_index: tab };
  return [
    {
      placement,
      obj: {
        type: PacketType.CUSTOM_TOOL_START,
        tool_name: "spawn_agent",
        display_name: "Start agent",
      },
    },
    {
      placement,
      obj: {
        type: PacketType.CUSTOM_TOOL_ARGS,
        tool_name: "spawn_agent",
        tool_args: { task_name: name, message: task },
      },
    },
    { placement, obj: { type: PacketType.SECTION_END } },
  ];
}

function step(tab: number, packets: CustomToolPacket[]): TransformedStep {
  return {
    key: `1-${tab}`,
    groupKey: `1-${tab}`,
    turnIndex: 1,
    tabIndex: tab,
    packets,
    nestedCalls: [],
    streamPackets: packets,
    codeMode: null,
  };
}

const STATUS: ChatSessionStatus = {
  is_processing: false,
  current_stream: null,
  has_active_subagents: true,
  has_startable_input: false,
  latest_response_id: 1,
  approvals_version: "",
};

function agent(
  id: string,
  path: string,
  status: ChatSubagent["status"],
  activity: string | null
): ChatSubagent {
  return {
    id,
    path,
    status,
    stopped_by_user: false,
    started_at: new Date(Date.now() - 5_000).toISOString(),
    stream_id: status === "running" ? 7 : null,
    activity_tool: activity,
  };
}

beforeEach(() => {
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: "s" });
  useChatSessionStore.getState().createSession("s");
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    const body = String(input).endsWith("/agents")
      ? [
          agent("a-1", "/root/alpha", "running", "web_search"),
          agent("b-1", "/root/beta", "complete", null),
        ]
      : STATUS;
    return new Response(JSON.stringify(body), { status: 200 });
  });
});

afterEach(() => jest.restoreAllMocks());

test("consecutive spawns of a turn form one step, which the group card renders", () => {
  const alpha = spawn(0, "alpha", "Find sources");
  const beta = spawn(1, "beta", "Check facts");
  const [grouped, ...rest] = groupSpawnSteps([step(0, alpha), step(1, beta)]);
  expect(rest).toEqual([]);
  expect(grouped?.packets).toEqual([...alpha, ...beta]);
  expect(findRenderer({ packets: grouped?.packets ?? [] })).toBe(
    AgentGroupRenderer
  );
  // A lone spawn keeps its own step
  expect(groupSpawnSteps([step(0, alpha)])).toEqual([step(0, alpha)]);
  // Parallel calls can take their own turns: they still form one card, with
  // one row per call
  const gamma = spawn(0, "gamma", "Draft", 2);
  const [acrossTurns] = groupSpawnSteps([step(0, alpha), step(0, gamma)]);
  expect(agentToolCalls(acrossTurns?.packets ?? []).map((c) => c.name)).toEqual(
    ["alpha", "gamma"]
  );
  expect(findRenderer({ packets: alpha })).toBe(AgentToolRenderer);
});

test("the card counts the subagents and who works, and a row opens its agent", async () => {
  render(
    <AgentGroupRenderer
      packets={[
        ...spawn(0, "alpha", "Find sources"),
        ...spawn(1, "beta", "Check facts"),
      ]}
      nestedCalls={[]}
      state={{}}
      onComplete={jest.fn()}
      renderType={RenderType.FULL}
      animate={false}
      stopPacketSeen={false}
    >
      {(results) => (
        <div>
          {results.map((result, index) => (
            <div key={index}>
              <span data-testid="status">
                {toPlainString(result.status ?? "")}
              </span>
              <div data-testid="accessory">{result.headerAccessory}</div>
              <div data-testid="body">{result.content}</div>
            </div>
          ))}
        </div>
      )}
    </AgentGroupRenderer>
  );

  expect(screen.getByTestId("status")).toHaveTextContent("2 subagents");
  expect(await screen.findByText("1 working")).toBeVisible();
  expect(screen.getByText("Using web_search")).toBeVisible();
  // A finished agent shows its task
  expect(screen.getByText("Check facts")).toBeVisible();

  act(() => screen.getByRole("button", { name: "Open alpha" }).click());
  const panel = useChatSessionStore.getState().sessions.get("s")?.rightPanel;
  expect(panel?.activeId).toBe("agent:a-1");
  expect(panel?.agentTabs).toEqual([{ agentId: "a-1", name: "alpha" }]);
});
