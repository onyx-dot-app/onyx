import { MCPConnectionStatus } from "@/lib/mcp/types";
import { act, renderHook } from "@testing-library/react";
import { sendMessage } from "@/app/app/services/lib";
import { ReadableStream } from "node:stream/web";
import {
  applyChatPluginIntent,
  chatPluginIntentLoadState,
  chatPluginsForAgent,
  enabledChatToolIds,
  effectiveChatForcedToolId,
  isChatPluginEnabled,
  memberPluginChatHref,
  memberPluginsHref,
  parseChatPluginIntent,
  safeChatReturnTo,
  setChatPluginEnabled,
  withoutChatPluginIntent,
} from "@/lib/plugins/chat";
import { buildMemberPlugins } from "@/lib/plugins/member";
import { MCPServerStatus, type MCPServer } from "@/lib/mcp/types";
import { useToolConfiguration } from "@/lib/tools/hooks";
import type { ToolSnapshot } from "@/lib/tools/types";

let mockChatId: string | null = "chat-a";
let mockAgentId: number | null = null;
let mockProjectId: number | null = null;

jest.mock("@/lib/position/hooks", () => ({
  useAppPosition: () => ({
    chat: () => mockChatId,
    agent: () => mockAgentId,
    project: () => mockProjectId,
  }),
}));
jest.mock("@/lib/agents/hooks", () => ({
  useActiveAgent: () => ({ id: 5 }),
}));

function tool(id: number, overrides: Partial<ToolSnapshot> = {}): ToolSnapshot {
  return {
    id,
    name: `tool-${id}`,
    display_name: `Tool ${id}`,
    description: "Read project records",
    definition: {},
    custom_headers: [],
    in_code_tool_id: null,
    passthrough_auth: false,
    enabled: true,
    chat_selectable: true,
    agent_creation_selectable: true,
    default_enabled: false,
    ...overrides,
  };
}

const server: MCPServer = {
  id: 7,
  name: "Team projects",
  server_url: "https://projects.example.com/mcp",
  owner: "admin@example.com",
  status: MCPServerStatus.CONNECTED,
  is_public: true,
  groups: [],
  users: [],
  tool_count: 3,
  connection_status: MCPConnectionStatus.CONNECTED,
  default_chat_enabled: false,
};
const tools = [
  tool(1, { in_code_tool_id: "SearchTool", definition: null }),
  tool(2, { in_code_tool_id: "FileReaderTool", chat_selectable: false }),
  tool(10, { mcp_server_id: 7, definition: null }),
  tool(11, { mcp_server_id: 7, definition: null }),
  tool(20),
];
const plugins = buildMemberPlugins([server], [...tools, tool(21)], {
  kind: "loaded",
  tokens: [],
});

test("Chat excludes external apps with colliding OpenAPI IDs and rejects their intents", () => {
  const catalog = buildMemberPlugins(
    [],
    [tool(7)],
    { kind: "loaded", tokens: [] },
    [
      {
        id: 7,
        name: "Project tracker",
        app_type: "CUSTOM",
        credential_keys: [],
        credential_values: {},
        authenticated: true,
        supports_oauth: false,
      },
    ]
  );
  const chat = chatPluginsForAgent(catalog, { id: 5, tools: [tool(7)] });
  expect(chat.map(({ plugin }) => plugin.kind)).toEqual(["openapi"]);
  expect(
    parseChatPluginIntent(
      new URLSearchParams("pluginKind=external-app&pluginId=7")
    )
  ).toBeNull();
});
const groups = chatPluginsForAgent(plugins, { id: 5, tools });

describe("effective forced tool selection", () => {
  const optedOutPlugins = buildMemberPlugins(
    [{ ...server, user_enabled_in_chat: false }],
    tools.map((entry) => ({ ...entry, user_enabled_in_chat: false })),
    { kind: "loaded", tokens: [] }
  );

  test.each([10, 20])("suppresses default Chat opt-out for tool %i", (id) => {
    expect(
      effectiveChatForcedToolId({
        requestedToolId: id,
        agent: { id: 0, tools },
        plugins: optedOutPlugins,
      })
    ).toBeNull();
  });

  test.each([10, 20])("preserves custom-agent forced tool %i", (id) => {
    expect(
      effectiveChatForcedToolId({
        requestedToolId: id,
        agent: { id: 5, tools },
        plugins: optedOutPlugins,
      })
    ).toBe(id);
  });

  test.each([10, 20])(
    "keeps persisted choice %i when suppressing a send",
    (id) => {
      const { result, unmount } = renderHook(() => useToolConfiguration());
      act(() => result.current.setToolState(id, () => "forced"));
      unmount();
      const restored = renderHook(() => useToolConfiguration());
      expect(restored.result.current.forcedToolId).toBe(id);
      expect(
        effectiveChatForcedToolId({
          requestedToolId: restored.result.current.forcedToolId,
          agent: { id: 0, tools },
          plugins: optedOutPlugins,
        })
      ).toBeNull();
      expect(restored.result.current.forcedToolId).toBe(id);
    }
  );

  test("preserves built-in Search even when plugins are opted out", () => {
    expect(
      effectiveChatForcedToolId({
        requestedToolId: 1,
        agent: { id: 0, tools },
        plugins: optedOutPlugins,
      })
    ).toBe(1);
  });

  test.each([10, 20])(
    "suppresses default Chat tool %i until its metadata loads",
    (id) => {
      expect(
        effectiveChatForcedToolId({
          requestedToolId: id,
          agent: { id: 0, tools },
          plugins: [],
        })
      ).toBeNull();
      expect(
        effectiveChatForcedToolId({
          requestedToolId: id,
          agent: { id: 0, tools },
          plugins: buildMemberPlugins([], [tool(999)], {
            kind: "loaded",
            tokens: [],
          }),
        })
      ).toBeNull();
    }
  );

  test.each([1, 10, 20])(
    "preserves custom-agent tool %i without plugin metadata",
    (id) => {
      expect(
        effectiveChatForcedToolId({
          requestedToolId: id,
          agent: { id: 5, tools },
          plugins: [],
        })
      ).toBe(id);
    }
  );

  test("preserves default Chat forced Search before plugin metadata loads", () => {
    expect(
      effectiveChatForcedToolId({
        requestedToolId: 1,
        agent: { id: 0, tools },
        plugins: [],
      })
    ).toBe(1);
  });

  test.each([null, 999])("does not force detached or unset tool %s", (id) => {
    expect(
      effectiveChatForcedToolId({
        requestedToolId: id,
        agent: { id: 0, tools },
        plugins,
      })
    ).toBeNull();
  });

  test("preserves attached plugins without opt-out and handles no agent", () => {
    expect(
      effectiveChatForcedToolId({
        requestedToolId: 20,
        agent: { id: 0, tools },
        plugins,
      })
    ).toBe(20);
    expect(
      effectiveChatForcedToolId({
        requestedToolId: 20,
        agent: undefined,
        plugins,
      })
    ).toBeNull();
  });
});

function mcpGroup() {
  const group = groups.find(({ plugin }) => plugin.kind === "mcp");
  if (!group) throw new Error("Missing MCP group");
  return group;
}

beforeEach(() => {
  sessionStorage.clear();
  mockChatId = "chat-a";
  mockAgentId = null;
  mockProjectId = null;
});
afterEach(() => jest.restoreAllMocks());

test("groups only attached tools and preserves custom-agent access outside default chat", () => {
  expect(
    groups.map(({ plugin, toolIds }) => ({ kind: plugin.kind, toolIds }))
  ).toEqual([
    { kind: "mcp", toolIds: [10, 11] },
    { kind: "openapi", toolIds: [20] },
  ]);
  expect(
    chatPluginsForAgent(plugins, {
      id: 5,
      tools: [tool(30, { mcp_server_id: 99 })],
    })
  ).toEqual([]);
  expect(
    chatPluginsForAgent(plugins, {
      id: 5,
      tools: [tool(20, { enabled: false })],
    })
  ).toEqual([]);
});

test("personal default Chat opt-out does not change custom-agent plugins", () => {
  const catalog = buildMemberPlugins(
    [{ ...server, default_chat_enabled: true, user_enabled_in_chat: false }],
    tools,
    { kind: "loaded", tokens: [] }
  );
  expect(
    chatPluginsForAgent(catalog, { id: 0, tools }).map(
      ({ plugin }) => plugin.kind
    )
  ).toEqual(["openapi"]);
  expect(
    chatPluginsForAgent(catalog, { id: 5, tools }).map(
      ({ plugin }) => plugin.kind
    )
  ).toEqual(["mcp", "openapi"]);
});

test("OpenAPI personal opt-out stays in the directory and affects only default Chat", () => {
  const personalTools = [tool(20, { user_enabled_in_chat: false }), tool(21)];
  const catalog = buildMemberPlugins([], personalTools, {
    kind: "loaded",
    tokens: [],
  });
  expect(catalog).toHaveLength(2);
  expect(
    chatPluginsForAgent(catalog, { id: 0, tools: personalTools }).flatMap(
      ({ toolIds }) => toolIds
    )
  ).toEqual([21]);
  expect(
    chatPluginsForAgent(catalog, { id: 5, tools: personalTools }).flatMap(
      ({ toolIds }) => toolIds
    )
  ).toEqual([20, 21]);
});

test("group enable preserves a forced tool and group disable releases only its own forced tool", () => {
  const { result } = renderHook(() => useToolConfiguration());
  act(() => {
    result.current.setToolState(10, () => "forced");
    result.current.setToolState(11, () => "disabled");
  });
  expect(isChatPluginEnabled(mcpGroup(), result.current)).toBe(true);
  act(() => setChatPluginEnabled(mcpGroup(), true, result.current));
  expect(result.current.forcedToolId).toBe(10);
  expect(result.current.disabledToolIds).toEqual([]);
  act(() => setChatPluginEnabled(mcpGroup(), false, result.current));
  expect(result.current.forcedToolId).toBeNull();
  expect(result.current.disabledToolIds).toEqual([10, 11]);
  act(() => result.current.setToolState(1, () => "forced"));
  act(() => setChatPluginEnabled(mcpGroup(), true, result.current));
  expect(result.current.forcedToolId).toBe(1);
});

test("a new attached MCP tool starts neutral after the existing group was disabled", () => {
  const { result } = renderHook(() => useToolConfiguration());
  act(() => setChatPluginEnabled(mcpGroup(), false, result.current));
  const expanded = chatPluginsForAgent(plugins, {
    id: 5,
    tools: [...tools, tool(12, { mcp_server_id: 7 })],
  })[0];
  if (!expanded) throw new Error("Missing expanded group");
  expect(expanded.toolIds).toEqual([10, 11, 12]);
  expect(result.current.stateOf(12)).toBeNull();
  expect(isChatPluginEnabled(expanded, result.current)).toBe(true);
});

test("chat plugin choices survive a reload and stay separate between chats", () => {
  const first = renderHook(() => useToolConfiguration());
  act(() => setChatPluginEnabled(mcpGroup(), false, first.result.current));
  first.unmount();
  const second = renderHook(() => useToolConfiguration());
  expect(second.result.current.disabledToolIds).toEqual([10, 11]);
  mockChatId = "chat-b";
  second.rerender();
  expect(isChatPluginEnabled(mcpGroup(), second.result.current)).toBe(true);
  act(() => second.result.current.setToolState(20, () => "disabled"));
  mockChatId = "chat-a";
  second.rerender();
  expect(second.result.current.disabledToolIds).toEqual([10, 11]);
});

test("browsing from a new project chat hands its configuration back to that composer", () => {
  mockChatId = null;
  mockProjectId = 9;
  const first = renderHook(() => useToolConfiguration());
  act(() => setChatPluginEnabled(mcpGroup(), false, first.result.current));
  act(() => first.result.current.handOffToNewChatWith(5, 9));
  first.unmount();
  const second = renderHook(() => useToolConfiguration());
  expect(second.result.current.disabledToolIds).toEqual([10, 11]);
  expect(sessionStorage.getItem("onyx:tools:new:5:9")).toBeNull();
  second.unmount();
  expect(
    renderHook(() => useToolConfiguration()).result.current.disabledToolIds
  ).toEqual([]);
});

test("Use in chat waits for the configuration and cannot attach a workspace plugin", () => {
  const { result } = renderHook(() => useToolConfiguration());
  act(() => setChatPluginEnabled(mcpGroup(), false, result.current));
  act(() => {
    expect(
      applyChatPluginIntent({ kind: "mcp", id: 7 }, groups, {
        ...result.current,
        ready: false,
      })
    ).toBe(false);
  });
  expect(result.current.disabledToolIds).toEqual([10, 11]);
  act(() => {
    expect(
      applyChatPluginIntent({ kind: "openapi", id: 21 }, groups, result.current)
    ).toBe(false);
  });
  expect(result.current.disabledToolIds).toEqual([10, 11]);
  act(() => {
    expect(
      applyChatPluginIntent({ kind: "mcp", id: 7 }, groups, result.current)
    ).toBe(true);
  });
  expect(isChatPluginEnabled(mcpGroup(), result.current)).toBe(true);
  expect(result.current.disabledToolIds).toEqual([]);
});

test("MCP chat intents ignore unrelated tool loading failures", () => {
  expect(
    chatPluginIntentLoadState(
      { kind: "mcp", id: 7 },
      {
        plugins,
        loading: { servers: false, tools: true },
        errors: {
          tools: new Error("Tools unavailable"),
        },
      }
    )
  ).toBe("loaded");
});

test("static-header OpenAPI intent applies despite an unrelated OAuth 503", () => {
  const staticHeaderTool = tool(20, {
    custom_headers: [{ key: "Authorization", value: "Bearer workspace-key" }],
  });
  const memberPlugins = {
    plugins: buildMemberPlugins(
      [],
      [staticHeaderTool, tool(21, { oauth_config_id: 4 })],
      { kind: "error" }
    ),
    loading: { servers: false, tools: false },
    errors: {},
  };
  const { result } = renderHook(() => useToolConfiguration());
  act(() => result.current.setToolState(20, () => "disabled"));
  expect(
    chatPluginIntentLoadState({ kind: "openapi", id: 20 }, memberPlugins)
  ).toBe("loaded");
  act(() => {
    applyChatPluginIntent(
      { kind: "openapi", id: 20 },
      chatPluginsForAgent(memberPlugins.plugins, {
        id: 5,
        tools: [staticHeaderTool],
      }),
      result.current
    );
  });
  expect(result.current.disabledToolIds).toEqual([]);
});

test("MCP chat intents wait for their roster and report server errors without waiting", () => {
  expect(
    chatPluginIntentLoadState(
      { kind: "mcp", id: 7 },
      {
        plugins,
        loading: { servers: true, tools: false },
        errors: {},
      }
    )
  ).toBe("loading");
  expect(
    chatPluginIntentLoadState(
      { kind: "mcp", id: 7 },
      {
        plugins,
        loading: { servers: true, tools: false },
        errors: { servers: new Error("MCP unavailable") },
      }
    )
  ).toBe("error");
});

test("OpenAPI chat intents wait for tools and ignore MCP failures", () => {
  const reference = { kind: "openapi", id: 20 } as const;
  expect(
    chatPluginIntentLoadState(reference, {
      plugins,
      loading: { servers: true, tools: false },
      errors: { servers: new Error("MCP unavailable") },
    })
  ).toBe("loaded");
  expect(
    chatPluginIntentLoadState(reference, {
      plugins,
      loading: { servers: false, tools: true },
      errors: {},
    })
  ).toBe("loading");
});

test.each([
  ["no authentication", tool(20)],
  [
    "static headers",
    tool(20, {
      custom_headers: [{ key: "X-Api-Key", value: "workspace-key" }],
    }),
  ],
  ["pass-through authentication", tool(20, { passthrough_auth: true })],
] satisfies [string, ToolSnapshot][])(
  "%s OpenAPI intents ignore pending and failed OAuth status",
  (_name, targetTool) => {
    expect(
      chatPluginIntentLoadState(
        { kind: "openapi", id: 20 },
        {
          plugins: buildMemberPlugins([], [targetTool], { kind: "loading" }),
          loading: { servers: false, tools: false },
          errors: {},
        }
      )
    ).toBe("loaded");
    expect(
      chatPluginIntentLoadState(
        { kind: "openapi", id: 20 },
        {
          plugins: buildMemberPlugins([], [targetTool], { kind: "error" }),
          loading: { servers: false, tools: false },
          errors: {},
        }
      )
    ).toBe("loaded");
  }
);

test("OpenAPI chat intents report tool errors and wait for roster resolution before checking OAuth", () => {
  const loading = { servers: false, tools: true };
  expect(
    chatPluginIntentLoadState(
      { kind: "openapi", id: 20 },
      {
        plugins: [],
        loading,
        errors: { tools: new Error("Tools unavailable") },
      }
    )
  ).toBe("error");
  expect(
    chatPluginIntentLoadState(
      { kind: "openapi", id: 20 },
      {
        plugins: [],
        loading,
        errors: {},
      }
    )
  ).toBe("loading");
});

test("OAuth OpenAPI intents still wait for and report their own status", () => {
  const oauthTool = tool(20, { oauth_config_id: 4 });
  const reference = { kind: "openapi", id: 20 } as const;
  expect(
    chatPluginIntentLoadState(reference, {
      plugins: buildMemberPlugins([], [oauthTool], { kind: "loading" }),
      loading: { servers: false, tools: false },
      errors: {},
    })
  ).toBe("loading");
  expect(
    chatPluginIntentLoadState(reference, {
      plugins: buildMemberPlugins([], [oauthTool], { kind: "error" }),
      loading: { servers: false, tools: false },
      errors: {},
    })
  ).toBe("error");
  expect(
    chatPluginIntentLoadState(reference, {
      plugins: buildMemberPlugins([], [oauthTool], {
        kind: "loaded",
        tokens: [],
      }),
      loading: { servers: false, tools: false },
      errors: {},
    })
  ).toBe("loaded");
});

test.each(["-7", "0", "7.5", "7oops", "9007199254740992"])(
  "rejects an invalid plugin identity %s",
  (id) => {
    expect(
      parseChatPluginIntent(
        new URLSearchParams({ pluginKind: "mcp", pluginId: id })
      )
    ).toBeNull();
    expect(
      parseChatPluginIntent(new URLSearchParams("pluginKind=mcp&pluginId=7"))
    ).toEqual({ kind: "mcp", id: 7 });
  }
);

test("clears only intent fields and validates the browse return destination", () => {
  const query = new URLSearchParams(
    "chatId=chat-a&temperature=0&pluginKind=mcp&pluginId=7"
  );
  expect(withoutChatPluginIntent(query).toString()).toBe(
    "chatId=chat-a&temperature=0"
  );
  expect(safeChatReturnTo("https://evil.example/app?chatId=chat-a")).toBe(
    "/app"
  );
  expect(safeChatReturnTo("//evil.example/app")).toBe("/app");
  expect(safeChatReturnTo("/app/plugins?agentId=5")).toBe("/app");
  expect(
    safeChatReturnTo(
      "/app?projectId=9&submit-on-load=true&user-prompt=send#section"
    )
  ).toBe("/app?projectId=9");
  expect(memberPluginsHref("/app?chatId=chat-a")).toBe(
    "/app/plugins?returnTo=%2Fapp%3FchatId%3Dchat-a"
  );
  expect(memberPluginChatHref({ kind: "mcp", id: 7 }, "/app?agentId=5")).toBe(
    "/app?agentId=5&pluginKind=mcp&pluginId=7"
  );
});

test("group selection serializes through the send service and neutral omits the whitelist", async () => {
  const requests: unknown[] = [];
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input, init) => {
      expect(input).toBe("/api/chat/send-chat-message");
      if (typeof init?.body !== "string")
        throw new Error("Expected JSON request body");
      requests.push(JSON.parse(init.body));
      const response = new Response("", { status: 200 });
      Object.defineProperty(response, "body", {
        value: new ReadableStream({
          start(controller) {
            controller.close();
          },
        }),
      });
      return response;
    });
  const { result } = renderHook(() => useToolConfiguration());
  act(() => {
    result.current.setToolState(10, () => "forced");
    setChatPluginEnabled(mcpGroup(), false, result.current);
  });
  await sendMessage({
    message: "Read team projects",
    chatSessionId: "chat-a",
    parentMessageId: null,
    filters: null,
    enabledToolIds: enabledChatToolIds(tools, result.current),
    forcedToolId: result.current.forcedToolId,
  }).next();
  expect(requests[0]).toMatchObject({
    message: "Read team projects",
    chat_session_id: "chat-a",
    allowed_tool_ids: [1, 2, 20],
    forced_tool_id: null,
  });
  act(() => setChatPluginEnabled(mcpGroup(), true, result.current));
  await sendMessage({
    message: "Read all projects",
    chatSessionId: "chat-a",
    parentMessageId: null,
    filters: null,
    enabledToolIds: enabledChatToolIds(tools, result.current),
  }).next();
  expect(requests[1]).toMatchObject({
    message: "Read all projects",
    chat_session_id: "chat-a",
  });
  expect(requests[1]).not.toHaveProperty("allowed_tool_ids");
  expect(fetchSpy).toHaveBeenCalledTimes(2);
});
