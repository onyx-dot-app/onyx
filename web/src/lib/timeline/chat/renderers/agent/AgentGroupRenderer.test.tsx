import { act, render, screen, waitFor } from "@tests/setup/test-utils";
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
import { MAX_LISTED_SUBAGENTS } from "@/lib/chat/hooks";
import { SubagentLinksContext } from "@/lib/chat/subagents";
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

/** A Claude-style spawn, whose description names the agent. */
function claudeSpawn(tab: number, description: string): CustomToolPacket[] {
  const placement = { turn_index: 1, tab_index: tab };
  return [
    {
      placement,
      obj: {
        type: PacketType.CUSTOM_TOOL_START,
        tool_name: "agent",
        display_name: "Start agent",
      },
    },
    {
      placement,
      obj: {
        type: PacketType.CUSTOM_TOOL_ARGS,
        tool_name: "agent",
        tool_args: { description, prompt: "Review it" },
      },
    },
    { placement, obj: { type: PacketType.SECTION_END } },
  ];
}

/** A spawn that the server refused, such as for a name in use. */
function refusedSpawn(tab: number, name: string): CustomToolPacket[] {
  const [start, args, end] = spawn(tab, name, "Again");
  if (!start || !args || !end) return [];
  return [
    start,
    args,
    {
      placement: start.placement,
      obj: {
        type: PacketType.CUSTOM_TOOL_DELTA,
        tool_name: "spawn_agent",
        response_type: "text",
        error: {
          is_auth_error: false,
          is_unreachable: false,
          status_code: 400,
          message: "An agent already has this name.",
        },
      },
    },
    end,
  ];
}

function renderCard(packets: CustomToolPacket[]) {
  render(
    <AgentGroupRenderer
      packets={packets}
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
              <div data-testid="accessory">{result.headerAccessory}</div>
              <div data-testid="body">{result.content}</div>
            </div>
          ))}
        </div>
      )}
    </AgentGroupRenderer>
  );
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
    latest_run_id: 1,
    stream_id: status === "running" ? 7 : null,
    activity_tool: activity,
    model: null,
    duration_seconds: status === "complete" ? 42 : null,
  };
}

function shownSubagent(): string | null {
  return new URLSearchParams(window.location.search).get("subagent");
}

beforeEach(() => {
  window.history.replaceState(null, "", "/app?chatId=s");
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

test("the group counts the subagents by state, and a card opens its agent in the main view", async () => {
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
  expect(await screen.findByText("1 working · 1 done")).toBeVisible();
  expect(screen.getByText("Using web_search")).toBeVisible();
  expect(screen.getByText("Running")).toBeVisible();
  // A finished agent shows its task and its time, without its state
  expect(screen.getByText("Check facts")).toBeVisible();
  expect(screen.getByText("42s")).toBeVisible();
  expect(screen.queryByText("Completed")).toBeNull();

  act(() => screen.getByRole("button", { name: "Open alpha" }).click());
  expect(shownSubagent()).toBe("a-1");
});

test("refused spawns count as failed and link to no earlier agent of their name", async () => {
  // beta already exists; both spawns were refused before any agent started
  renderCard([...refusedSpawn(0, "beta"), ...refusedSpawn(1, "delta")]);
  expect(await screen.findByText("2 failed")).toBeVisible();
  expect(screen.queryByText(/done/)).toBeNull();
  expect(screen.queryByRole("button", { name: "Open beta" })).toBeNull();
});

test("a Claude spawn whose description has a slash opens the agent the server named", async () => {
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    const body = String(input).endsWith("/agents")
      ? [
          agent("c-1", "/root/auth-session", "running", null),
          agent("d-1", "/root/ui", "running", null),
        ]
      : STATUS;
    return new Response(JSON.stringify(body), { status: 200 });
  });
  renderCard([...claudeSpawn(0, "auth/session"), ...claudeSpawn(1, "ui")]);
  const row = await screen.findByRole("button", { name: "Open auth/session" });
  act(() => row.click());
  expect(shownSubagent()).toBe("c-1");
});

test("on a page without subagent links, a finished group does not read as working and opens nothing", async () => {
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    const body = String(input).endsWith("/agents")
      ? [
          agent("a-1", "/root/alpha", "complete", null),
          agent("b-1", "/root/beta", "complete", null),
        ]
      : STATUS;
    return new Response(JSON.stringify(body), { status: 200 });
  });
  render(
    <SubagentLinksContext.Provider value={false}>
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
                <div data-testid="accessory">{result.headerAccessory}</div>
                <div data-testid="body">{result.content}</div>
              </div>
            ))}
          </div>
        )}
      </AgentGroupRenderer>
    </SubagentLinksContext.Provider>
  );

  expect(await screen.findByText("2 done")).toBeVisible();
  expect(screen.queryByText(/working/)).toBeNull();
  expect(screen.queryByRole("button", { name: "Open alpha" })).toBeNull();
});

test("a chat outside the session store does not show finished spawns as working", async () => {
  // A shared chat has no current session, so no agents list
  useChatSessionStore.setState({ currentSessionId: null });
  renderCard([
    ...spawn(0, "alpha", "Find sources"),
    ...spawn(1, "beta", "Check facts"),
  ]);

  expect(await screen.findByText("Check facts")).toBeVisible();
  expect(screen.queryByText(/working|Starting/)).toBeNull();
  expect(screen.queryByRole("button", { name: "Open alpha" })).toBeNull();
});

test("a full agents list that omits a finished spawn does not read as working", async () => {
  // The endpoint returns the newest agents only; alpha is older than all
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    const body = String(input).endsWith("/agents")
      ? Array.from({ length: MAX_LISTED_SUBAGENTS }, (_, index) =>
          agent(`f-${index}`, `/root/fill-${index}`, "complete", null)
        )
      : STATUS;
    return new Response(JSON.stringify(body), { status: 200 });
  });
  renderCard(spawn(0, "alpha", "Find sources"));

  // Until the full list loads, the spawn still starts
  await waitFor(() =>
    expect(screen.queryByText(/working|Starting/)).toBeNull()
  );
  expect(screen.getByText("Find sources")).toBeVisible();
});
