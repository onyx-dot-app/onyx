import { act, renderHook, waitFor } from "@testing-library/react";
import useSWR, { SWRConfig, useSWRConfig } from "swr";
import {
  buildMemberPlugins,
  canUseMemberPlugin,
  connectMemberPlugin,
  disconnectMemberPlugin,
  memberPluginReference,
  saveMemberOpenAPIPreferences,
  verifyMemberPluginConnection,
  useMemberPlugins,
  type MemberPlugin,
} from "@/lib/plugins/member";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  MCPConnectionStatus,
  MCPServerStatus,
  type MCPServer,
} from "@/lib/mcp/types";
import type { ToolSnapshot } from "@/lib/tools/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useSettings } from "@/lib/settings/hooks";
import type { ExternalAppUserResponse } from "@/app/craft/v1/apps/registry";

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: jest.fn(() => ({ onyx_craft_enabled: false })),
}));

function externalApp(
  overrides: Partial<ExternalAppUserResponse> = {}
): ExternalAppUserResponse {
  return {
    id: 7,
    name: "Project tracker",
    app_type: "CUSTOM",
    credential_keys: ["api_key"],
    credential_values: {},
    authenticated: false,
    supports_oauth: false,
    ...overrides,
  };
}

function appPlugin(
  overrides: Partial<ExternalAppUserResponse> = {}
): MemberPlugin {
  const plugin = buildMemberPlugins([], [], { kind: "loaded", tokens: [] }, [
    externalApp(overrides),
  ])[0];
  if (!plugin) throw new Error("Missing app fixture");
  return plugin;
}

test.each([
  [{ supports_oauth: true }, { kind: "oauth" }],
  [{}, { kind: "credentials", fields: ["api_key"], thenOAuth: false }],
  [{ authenticated: true }, { kind: "connected", ownership: "user" }],
  [
    { authenticated: true, credential_keys: [] },
    { kind: "connected", ownership: "workspace" },
  ],
  [
    { authenticated: true, credential_keys: [], supports_oauth: true },
    { kind: "connected", ownership: "user" },
  ],
  [{ credential_keys: [] }, { kind: "unconfigured" }],
])(
  "classifies external app credential ownership and prioritizes OAuth",
  (overrides, connection) => {
    expect(appPlugin(overrides).connection).toEqual(connection);
  }
);

test("saves external app user credentials and verifies only its backend", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) => {
      if (input === "/api/build/apps/7/credentials") return new Response("{}");
      if (input === "/api/build/apps")
        return new Response(
          JSON.stringify([externalApp({ authenticated: true })])
        );
      throw new Error(`Unexpected endpoint ${input}`);
    });
  await connectMemberPlugin(appPlugin(), { api_key: "secret" });
  expect(fetchSpy).toHaveBeenCalledWith("/api/build/apps/7/credentials", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_credentials: { api_key: "secret" } }),
  });
  expect(fetchSpy.mock.calls.map(([input]) => input)).toEqual([
    "/api/build/apps/7/credentials",
    "/api/build/apps",
  ]);
});

test("disconnects external app personal credentials and preserves workspace credentials", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(new Response("{}"));
  await disconnectMemberPlugin(appPlugin({ authenticated: true }));
  await expect(
    disconnectMemberPlugin(
      appPlugin({ authenticated: true, credential_keys: [] })
    )
  ).rejects.toMatchObject({ reason: "unconfigured" });
  expect(fetchSpy.mock.calls).toEqual([
    ["/api/build/apps/7/credentials", { method: "DELETE" }],
  ]);
});

test("Craft loads external apps and uses authoritative MCP Craft authentication without OpenAPI", async () => {
  jest
    .mocked(useSettings)
    .mockReturnValue({ onyx_craft_enabled: true } as ReturnType<
      typeof useSettings
    >);
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) => {
      if (input === "/api/mcp/servers/craft")
        return new Response(
          JSON.stringify({
            mcp_servers: [
              server({
                available_in_craft: true,
                connection_status: MCPConnectionStatus.NOT_CONNECTED,
                craft_connected: false,
              }),
              server({ id: 8, available_in_craft: false }),
            ],
          })
        );
      if (input === "/api/build/apps")
        return new Response(JSON.stringify([externalApp()]));
      throw new Error(`Unexpected endpoint ${input}`);
    });
  const { result } = renderHook(() => useMemberPlugins({ surface: "craft" }), {
    wrapper: ({ children }) => (
      <SWRConfig
        value={{ provider: () => new Map(), shouldRetryOnError: false }}
      >
        {children}
      </SWRConfig>
    ),
  });
  await waitFor(() => expect(result.current.isLoading).toBe(false));
  expect(result.current.plugins.map(memberPluginReference)).toEqual([
    { kind: "external-app", id: 7 },
    { kind: "mcp", id: 7 },
  ]);
  expect(result.current.plugins[1]?.connection).toEqual({ kind: "oauth" });
  expect(fetchSpy.mock.calls.map(([input]) => input).sort()).toEqual([
    "/api/build/apps",
    "/api/mcp/servers/craft",
  ]);
  jest
    .mocked(useSettings)
    .mockReturnValue({ onyx_craft_enabled: false } as ReturnType<
      typeof useSettings
    >);
});

test("the unified directory includes external apps while Chat does not fetch them", async () => {
  jest
    .mocked(useSettings)
    .mockReturnValue({ onyx_craft_enabled: true } as ReturnType<
      typeof useSettings
    >);
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) => {
      if (input === "/api/mcp/servers")
        return new Response(JSON.stringify({ mcp_servers: [] }));
      if (input === "/api/build/apps")
        return new Response(JSON.stringify([externalApp()]));
      return new Response("[]");
    });
  const { result, rerender } = renderHook(
    ({ surface }: { surface: "chat" | "all" }) => useMemberPlugins({ surface }),
    {
      initialProps: { surface: "chat" },
      wrapper: ({ children }) => (
        <SWRConfig
          value={{ provider: () => new Map(), shouldRetryOnError: false }}
        >
          {children}
        </SWRConfig>
      ),
    }
  );
  await waitFor(() => expect(result.current.isLoading).toBe(false));
  expect(fetchSpy).not.toHaveBeenCalledWith("/api/build/apps");
  rerender({ surface: "all" });
  await waitFor(() =>
    expect(result.current.plugins.map(memberPluginReference)).toEqual([
      { kind: "external-app", id: 7 },
    ])
  );
  jest
    .mocked(useSettings)
    .mockReturnValue({ onyx_craft_enabled: false } as ReturnType<
      typeof useSettings
    >);
});

function server(overrides: Partial<MCPServer> = {}): MCPServer {
  return {
    id: 7,
    name: "Team notes",
    server_url: "",
    owner: "",
    status: MCPServerStatus.CONNECTED,
    is_public: true,
    groups: [],
    users: [],
    tool_count: 1,
    auth_type: MCPAuthenticationType.OAUTH,
    auth_performer: MCPAuthenticationPerformer.PER_USER,
    connection_status: MCPConnectionStatus.NOT_CONNECTED,
    ...overrides,
  };
}

function tool(overrides: Partial<ToolSnapshot> = {}): ToolSnapshot {
  return {
    id: 7,
    name: "notes",
    display_name: "Team notes",
    description: "Find team notes",
    definition: { openapi: "3.0.0", paths: {} },
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

function firstMCP(overrides: Partial<MCPServer> = {}): MemberPlugin {
  const plugin = buildMemberPlugins([server(overrides)], [], {
    kind: "loaded",
    tokens: [],
  })[0];
  if (!plugin) throw new Error("Missing plugin fixture");
  return plugin;
}

afterEach(() => jest.restoreAllMocks());

test("keeps native identities and excludes disabled or built-in tools", () => {
  const plugins = buildMemberPlugins(
    [server()],
    [
      tool(),
      tool({ id: 8, mcp_server_id: 7, definition: null }),
      tool({ id: 9, enabled: false }),
      tool({ id: 10, in_code_tool_id: "SearchTool" }),
    ],
    { kind: "loaded", tokens: [] }
  );
  expect(plugins.map(memberPluginReference)).toEqual([
    { kind: "mcp", id: 7 },
    { kind: "openapi", id: 7 },
  ]);
  expect(plugins[0]).toEqual({
    kind: "mcp",
    server: server(),
    tools: [tool({ id: 8, mcp_server_id: 7, definition: null })],
    connection: { kind: "oauth" },
  });
});

test.each([
  [
    {
      auth_type: MCPAuthenticationType.API_TOKEN,
      auth_performer: MCPAuthenticationPerformer.ADMIN,
      connection_status: MCPConnectionStatus.CONNECTED,
    },
    { kind: "connected", ownership: "workspace" },
  ],
  [
    {
      auth_type: MCPAuthenticationType.API_TOKEN,
      auth_performer: MCPAuthenticationPerformer.ADMIN,
    },
    { kind: "unconfigured" },
  ],
  [
    { auth_type: MCPAuthenticationType.API_TOKEN },
    { kind: "credentials", fields: ["api_key"], thenOAuth: false },
  ],
  [
    { auth_template: { headers: {}, required_fields: ["tenant", "api_key"] } },
    { kind: "credentials", fields: ["tenant", "api_key"], thenOAuth: true },
  ],
  [
    {
      auth_type: MCPAuthenticationType.PT_OAUTH,
      connection_status: MCPConnectionStatus.CONNECTED,
    },
    { kind: "connected", ownership: "session" },
  ],
  [
    {
      auth_type: MCPAuthenticationType.NONE,
      connection_status: MCPConnectionStatus.CONNECTED,
    },
    { kind: "connected", ownership: "none" },
  ],
  [
    { connection_status: MCPConnectionStatus.REAUTH_REQUIRED },
    { kind: "oauth" },
  ],
  [
    {
      auth_type: MCPAuthenticationType.NONE,
      auth_template: { headers: {}, required_fields: ["tenant"] },
    },
    { kind: "credentials", fields: ["tenant"], thenOAuth: false },
  ],
  [
    {
      auth_type: MCPAuthenticationType.PT_OAUTH,
      auth_template: { headers: {}, required_fields: ["tenant"] },
    },
    { kind: "credentials", fields: ["tenant"], thenOAuth: false },
  ],
  [
    {
      auth_type: MCPAuthenticationType.OAUTH,
      auth_performer: MCPAuthenticationPerformer.ADMIN,
      auth_template: { headers: {}, required_fields: ["tenant"] },
    },
    { kind: "unconfigured" },
  ],
  [{ connection_status: null }, { kind: "unavailable" }],
])(
  "classifies member authentication from resolved credentials",
  (overrides, connection) => {
    expect(firstMCP(overrides).connection).toEqual(connection);
  }
);

test("does not confuse global MCP status or default Chat policy with personal authentication", () => {
  const plugin = firstMCP({
    status: MCPServerStatus.DISCONNECTED,
    default_chat_enabled: false,
    connection_status: MCPConnectionStatus.CONNECTED,
  });
  expect(plugin.connection).toEqual({ kind: "connected", ownership: "user" });
  expect(canUseMemberPlugin(plugin)).toBe(true);
});

test("accepts unauthenticated OpenAPI tools with null custom headers", () => {
  const plugins = buildMemberPlugins([], [tool({ custom_headers: null })], {
    kind: "loaded",
    tokens: [],
  });
  expect(plugins[0]?.connection).toEqual({
    kind: "connected",
    ownership: "none",
  });
});

test("keeps OAuth loading, failed status, missing tokens, and expired grants distinct", () => {
  const oauthTool = tool({ oauth_config_id: 4 });
  expect(
    buildMemberPlugins([], [oauthTool], { kind: "loading" })[0]?.connection
  ).toEqual({ kind: "checking" });
  expect(
    buildMemberPlugins([], [oauthTool], { kind: "error" })[0]?.connection
  ).toEqual({ kind: "unavailable" });
  expect(
    buildMemberPlugins([], [oauthTool], { kind: "loaded", tokens: [] })[0]
      ?.connection
  ).toEqual({ kind: "oauth" });
  expect(
    buildMemberPlugins([], [oauthTool], {
      kind: "loaded",
      tokens: [{ oauth_config_id: 4, is_expired: true, expires_at: 1 }],
    })[0]?.connection
  ).toEqual({ kind: "oauth" });
  expect(
    buildMemberPlugins([], [oauthTool], {
      kind: "loaded",
      tokens: [{ oauth_config_id: 4, is_expired: false, expires_at: null }],
    })[0]?.connection
  ).toEqual({ kind: "connected", ownership: "user" });
});

test.each([false, true])(
  "expired OpenAPI grants require authentication unless refreshable=%s",
  (canRefresh) => {
    const plugin = buildMemberPlugins([], [tool({ oauth_config_id: 4 })], {
      kind: "loaded",
      tokens: [
        {
          oauth_config_id: 4,
          is_expired: true,
          expires_at: 1,
          can_refresh: canRefresh,
        },
      ],
    })[0];
    if (!plugin) throw new Error("Missing OpenAPI fixture");
    expect(plugin.connection).toEqual(
      canRefresh ? { kind: "connected", ownership: "user" } : { kind: "oauth" }
    );
    expect(canUseMemberPlugin(plugin)).toBe(canRefresh);
  }
);

test("preserves loaded sources while reporting an OAuth status failure", async () => {
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    if (input === "/api/mcp/servers")
      return new Response(JSON.stringify({ mcp_servers: [server()] }));
    if (input === "/api/tool")
      return new Response(JSON.stringify([tool({ oauth_config_id: 4 })]));
    if (input === "/api/user-oauth-token/status")
      return new Response(JSON.stringify({ detail: "Unavailable" }), {
        status: 503,
      });
    throw new Error(`Unexpected endpoint ${input}`);
  });
  const { result } = renderHook(() => useMemberPlugins(), {
    wrapper: ({ children }) => (
      <SWRConfig
        value={{ provider: () => new Map(), shouldRetryOnError: false }}
      >
        {children}
      </SWRConfig>
    ),
  });
  await waitFor(() =>
    expect(result.current.errors.oauth?.message).toContain("fetching")
  );
  expect(result.current.isLoading).toBe(false);
  expect(result.current.loading).toEqual({
    apps: false,
    servers: false,
    tools: false,
    oauth: false,
  });
  expect(
    result.current.plugins.map((plugin) => plugin.connection.kind)
  ).toEqual(["oauth", "unavailable"]);
});

test("loads separate attached MCP rosters for the default and custom agents", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) => {
      if (input === "/api/mcp/servers/persona/0")
        return new Response(JSON.stringify({ mcp_servers: [server()] }));
      if (input === "/api/mcp/servers/persona/5")
        return new Response(
          JSON.stringify({ mcp_servers: [server({ id: 8, is_public: false })] })
        );
      if (input === "/api/mcp/servers")
        return new Response(JSON.stringify({ mcp_servers: [] }));
      return new Response("[]");
    });
  const { result, rerender } = renderHook(
    ({ agentId }) => useMemberPlugins({ agentId }),
    {
      initialProps: { agentId: 0 },
      wrapper: ({ children }) => (
        <SWRConfig
          value={{ provider: () => new Map(), shouldRetryOnError: false }}
        >
          {children}
        </SWRConfig>
      ),
    }
  );
  await waitFor(() =>
    expect(result.current.plugins.map(memberPluginReference)).toEqual([
      { kind: "mcp", id: 7 },
    ])
  );
  rerender({ agentId: 5 });
  await waitFor(() =>
    expect(result.current.plugins.map(memberPluginReference)).toEqual([
      { kind: "mcp", id: 8 },
    ])
  );
  expect(fetchSpy).toHaveBeenCalledWith("/api/mcp/servers/persona/0");
  expect(fetchSpy).toHaveBeenCalledWith("/api/mcp/servers/persona/5");
  expect(fetchSpy).not.toHaveBeenCalledWith("/api/mcp/servers");
});

test("the member directory keeps its accessible catalog apart from an agent roster", async () => {
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    if (input === "/api/mcp/servers")
      return new Response(JSON.stringify({ mcp_servers: [server()] }));
    if (input === "/api/mcp/servers/persona/5")
      return new Response(
        JSON.stringify({ mcp_servers: [server({ id: 8, is_public: false })] })
      );
    return new Response("[]");
  });
  const { result } = renderHook(
    () => ({
      directory: useMemberPlugins(),
      chat: useMemberPlugins({ agentId: 5 }),
    }),
    {
      wrapper: ({ children }) => (
        <SWRConfig
          value={{ provider: () => new Map(), shouldRetryOnError: false }}
        >
          {children}
        </SWRConfig>
      ),
    }
  );
  await waitFor(() =>
    expect(result.current.chat.plugins.map(memberPluginReference)).toEqual([
      { kind: "mcp", id: 8 },
    ])
  );
  expect(result.current.directory.plugins.map(memberPluginReference)).toEqual([
    { kind: "mcp", id: 7 },
  ]);
});

test("the standalone member directory loads only its accessible MCP catalog", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) => {
      if (input === "/api/mcp/servers")
        return new Response(JSON.stringify({ mcp_servers: [server()] }));
      return new Response("[]");
    });
  const { result } = renderHook(() => useMemberPlugins(), {
    wrapper: ({ children }) => (
      <SWRConfig
        value={{ provider: () => new Map(), shouldRetryOnError: false }}
      >
        {children}
      </SWRConfig>
    ),
  });
  await waitFor(() =>
    expect(result.current.plugins.map(memberPluginReference)).toEqual([
      { kind: "mcp", id: 7 },
    ])
  );
  expect(fetchSpy.mock.calls.map(([input]) => String(input)).sort()).toEqual([
    "/api/mcp/servers",
    "/api/tool",
    "/api/user-oauth-token/status",
  ]);
});

test("refreshes agent and member connections within the active SWR provider", async () => {
  let generation = 1;
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    if (input === "/api/mcp/servers")
      return new Response(JSON.stringify({ mcp_servers: [server()] }));
    if (input === "/api/persona/2")
      return new Response(JSON.stringify({ generation }));
    return new Response("[]");
  });
  const { result } = renderHook(
    () => ({
      member: useMemberPlugins(),
      agent: useSWR<{ generation: number }>(
        SWR_KEYS.agent(2),
        async (key: string) => {
          const response = await fetch(key);
          return response.json();
        }
      ),
    }),
    {
      wrapper: ({ children }) => (
        <SWRConfig
          value={{ provider: () => new Map(), shouldRetryOnError: false }}
        >
          {children}
        </SWRConfig>
      ),
    }
  );
  await waitFor(() =>
    expect(result.current.agent.data).toEqual({ generation: 1 })
  );
  generation = 2;
  await act(async () => result.current.member.refresh());
  expect(result.current.agent.data).toEqual({ generation: 2 });
  expect(result.current.member.plugins.map(memberPluginReference)).toEqual([
    { kind: "mcp", id: 7 },
  ]);
});

describe("personal OpenAPI preferences", () => {
  function renderPreferences(tools?: ToolSnapshot[]) {
    const otherTools = [tool({ id: 99 })];
    const cache = new Map([
      [SWR_KEYS.openApiTools, { data: otherTools }],
      ...(tools ? [[SWR_KEYS.tools, { data: tools }] as const] : []),
    ]);
    return renderHook(
      () => ({
        mutate: useSWRConfig().mutate,
        tools: useSWR<ToolSnapshot[]>(tools ? SWR_KEYS.tools : null).data,
        admin: useSWR<ToolSnapshot[]>(SWR_KEYS.openApiTools).data,
      }),
      {
        wrapper: ({ children }) => (
          <SWRConfig value={{ provider: () => cache }}>{children}</SWRConfig>
        ),
      }
    );
  }

  test("optimistically updates only the personal flag and preserves other tools and admin data", async () => {
    let finish = (_response: Response) => {};
    const response = new Promise<Response>((resolve) => {
      finish = resolve;
    });
    const fetchSpy = jest.spyOn(global, "fetch").mockReturnValue(response);
    const original = tool({ id: 20, default_chat_enabled: true });
    const other = tool({ id: 21 });
    const { result } = renderPreferences([original, other]);
    let save: Promise<void> | undefined;
    act(() => {
      save = saveMemberOpenAPIPreferences(
        20,
        { enabled_in_chat: false },
        result.current.mutate
      );
    });
    await waitFor(() =>
      expect(result.current.tools).toEqual([
        { ...original, user_enabled_in_chat: false },
        other,
      ])
    );
    expect(result.current.admin).toEqual([tool({ id: 99 })]);
    await act(async () => {
      finish(new Response(JSON.stringify({ enabled_in_chat: false })));
      await save;
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy).toHaveBeenCalledWith("/api/tool/20/preferences", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled_in_chat: false }),
    });
    expect(result.current.tools?.[0]).toEqual({
      ...original,
      user_enabled_in_chat: false,
    });
  });

  test("rolls back rejected saves and retains workspace settings", async () => {
    let finish = (_response: Response) => {};
    jest.spyOn(global, "fetch").mockReturnValue(
      new Promise<Response>((resolve) => {
        finish = resolve;
      })
    );
    const original = tool({ id: 20, default_chat_enabled: true });
    const { result } = renderPreferences([original]);
    let error: unknown;
    let save: Promise<void> | undefined;
    act(() => {
      save = saveMemberOpenAPIPreferences(
        20,
        { enabled_in_chat: false },
        result.current.mutate
      ).catch((failure) => {
        error = failure;
      });
    });
    await waitFor(() =>
      expect(result.current.tools?.[0]?.user_enabled_in_chat).toBe(false)
    );
    await act(async () => {
      finish(
        new Response(JSON.stringify({ detail: "Workspace access changed" }), {
          status: 403,
        })
      );
      await save;
    });
    expect(error).toEqual(new Error("Workspace access changed"));
    expect(result.current.tools).toEqual([original]);
  });

  test("awaits the request without a mounted member tools cache", async () => {
    let finish = (_response: Response) => {};
    const fetchSpy = jest.spyOn(global, "fetch").mockReturnValue(
      new Promise<Response>((resolve) => {
        finish = resolve;
      })
    );
    const { result } = renderPreferences();
    let completed = false;
    const save = saveMemberOpenAPIPreferences(
      20,
      { enabled_in_chat: false },
      result.current.mutate
    ).then(() => {
      completed = true;
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(completed).toBe(false);
    await act(async () => {
      finish(new Response(JSON.stringify({ enabled_in_chat: false })));
      await save;
    });
    expect(completed).toBe(true);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(result.current.admin).toEqual([tool({ id: 99 })]);
  });
});

test("saves actual per-user credentials and verifies member authentication", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) => {
      if (input === "/api/mcp/user-credentials") return new Response("{}");
      if (input === "/api/mcp/servers")
        return new Response(
          JSON.stringify({
            mcp_servers: [
              server({
                auth_type: MCPAuthenticationType.API_TOKEN,
                connection_status: MCPConnectionStatus.CONNECTED,
              }),
            ],
          })
        );
      if (input === "/api/tool" || input === "/api/user-oauth-token/status")
        return new Response("[]");
      throw new Error(`Unexpected endpoint ${input}`);
    });
  await connectMemberPlugin(
    firstMCP({ auth_type: MCPAuthenticationType.API_TOKEN }),
    { api_key: "personal-secret" }
  );
  expect(fetchSpy).toHaveBeenCalledWith("/api/mcp/user-credentials", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      server_id: 7,
      credentials: { api_key: "personal-secret" },
      transport: "STREAMABLE_HTTP",
    }),
  });
  expect(fetchSpy.mock.calls.map(([input]) => input)).toEqual([
    "/api/mcp/user-credentials",
    "/api/mcp/servers",
  ]);
});

test.each([
  { agentId: 5, surface: "chat", endpoint: SWR_KEYS.agentMcpServers(5) },
  { agentId: 0, surface: "chat", endpoint: SWR_KEYS.agentMcpServers(0) },
  { agentId: undefined, surface: "craft", endpoint: SWR_KEYS.mcpServersCraft },
] as const)(
  "verifies personal MCP credentials through $endpoint",
  async ({ agentId, surface, endpoint }) => {
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockImplementation(async (input) => {
        if (input === "/api/mcp/user-credentials") return new Response("{}");
        if (input === endpoint)
          return new Response(
            JSON.stringify({
              mcp_servers: [
                server({
                  auth_type: MCPAuthenticationType.API_TOKEN,
                  connection_status: MCPConnectionStatus.CONNECTED,
                }),
              ],
            })
          );
        if (input === SWR_KEYS.mcpServers)
          return new Response(JSON.stringify({ mcp_servers: [] }));
        throw new Error(`Unexpected endpoint ${input}`);
      });
    await connectMemberPlugin(
      firstMCP({ auth_type: MCPAuthenticationType.API_TOKEN }),
      { api_key: "personal-secret" },
      { agentId, surface }
    );
    expect(fetchSpy.mock.calls.map(([input]) => input)).toEqual([
      "/api/mcp/user-credentials",
      endpoint,
    ]);
    await expect(
      verifyMemberPluginConnection({ kind: "mcp", id: 7 })
    ).rejects.toMatchObject({
      reason: "not_connected",
    });
  }
);

test("rejects blank required fields before saving and refuses a false credential success", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) => {
      if (input === "/api/mcp/user-credentials") return new Response("{}");
      if (input === "/api/mcp/servers")
        return new Response(JSON.stringify({ mcp_servers: [server()] }));
      return new Response("[]");
    });
  const plugin = firstMCP({ auth_type: MCPAuthenticationType.API_TOKEN });
  await expect(
    connectMemberPlugin(plugin, { api_key: " " })
  ).rejects.toMatchObject({ reason: "credentials_required" });
  expect(fetchSpy).not.toHaveBeenCalled();
  await expect(
    connectMemberPlugin(plugin, { api_key: "secret" })
  ).rejects.toMatchObject({ reason: "not_connected" });
  expect(fetchSpy).toHaveBeenCalledWith("/api/mcp/servers");
});

test("disconnects only personal credentials using the native endpoints", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(new Response("{}"));
  await disconnectMemberPlugin(
    firstMCP({ connection_status: MCPConnectionStatus.CONNECTED })
  );
  const openAPI = buildMemberPlugins([], [tool({ oauth_config_id: 4 })], {
    kind: "loaded",
    tokens: [{ oauth_config_id: 4, expires_at: null, is_expired: false }],
  })[0];
  if (!openAPI) throw new Error("Missing fixture");
  await disconnectMemberPlugin(openAPI);
  await expect(
    disconnectMemberPlugin(
      firstMCP({
        auth_performer: MCPAuthenticationPerformer.ADMIN,
        connection_status: MCPConnectionStatus.CONNECTED,
      })
    )
  ).rejects.toMatchObject({ reason: "unconfigured" });
  expect(fetchSpy.mock.calls).toEqual([
    ["/api/mcp/user-credentials/7", { method: "DELETE" }],
    ["/api/oauth-config/4/token", { method: "DELETE" }],
  ]);
});

test.each([
  MCPConnectionStatus.NOT_CONNECTED,
  MCPConnectionStatus.REAUTH_REQUIRED,
])(
  "reserves OAuth before network work and verifies the callback with saved credentials (%s)",
  async (connectionStatus) => {
    const popup = {
      closed: false,
      close: jest.fn(),
      location: { href: "about:blank" },
    } as unknown as Window;
    const openSpy = jest.spyOn(window, "open").mockReturnValue(popup);
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockImplementation(async (input) => {
        expect(openSpy).toHaveBeenCalledTimes(1);
        if (input === "/api/mcp/oauth/connect")
          return new Response(
            JSON.stringify({
              status: "authorization_required",
              authorization_url: "https://notes.example/oauth",
              server_id: 7,
              redirect_url: "/app",
            })
          );
        if (input === "/api/mcp/servers")
          return new Response(
            JSON.stringify({
              mcp_servers: [
                server({ connection_status: MCPConnectionStatus.CONNECTED }),
              ],
            })
          );
        return new Response("[]");
      });
    const promise = connectMemberPlugin(
      firstMCP({ connection_status: connectionStatus })
    );
    await waitFor(() =>
      expect(popup.location.href).toBe("https://notes.example/oauth")
    );
    const startRequest = fetchSpy.mock.calls[0]?.[1];
    const body: { return_path: string; force_reauthentication: boolean } =
      JSON.parse(String(startRequest?.body));
    expect(body.force_reauthentication).toBe(
      connectionStatus === MCPConnectionStatus.REAUTH_REQUIRED
    );
    const attempt = new URL(
      body.return_path,
      window.location.origin
    ).searchParams.get("attempt");
    await act(async () => {
      window.dispatchEvent(
        new MessageEvent("message", {
          origin: window.location.origin,
          source: popup,
          data: { type: "onyx:member-plugin-oauth-complete", attempt },
        })
      );
      await promise;
    });
    expect(popup.close).toHaveBeenCalledTimes(1);
    expect(fetchSpy).toHaveBeenCalledWith("/api/mcp/servers");
  }
);

test("connects an OpenAPI plugin through its real OAuth initiation endpoint", async () => {
  const popup = {
    closed: false,
    close: jest.fn(),
    location: { href: "about:blank" },
  } as unknown as Window;
  jest.spyOn(window, "open").mockReturnValue(popup);
  const oauthTool = tool({ oauth_config_id: 4 });
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) => {
      if (input === "/api/oauth-config/initiate")
        return new Response(
          JSON.stringify({
            authorization_url: "https://notes.example/oauth",
            state: "provider-state",
          })
        );
      if (input === "/api/mcp/servers")
        return new Response(JSON.stringify({ mcp_servers: [] }));
      if (input === "/api/tool")
        return new Response(JSON.stringify([oauthTool]));
      if (input === "/api/user-oauth-token/status")
        return new Response(
          JSON.stringify([
            { oauth_config_id: 4, expires_at: null, is_expired: false },
          ])
        );
      throw new Error(`Unexpected request ${input}`);
    });
  const plugin = buildMemberPlugins([], [oauthTool], {
    kind: "loaded",
    tokens: [],
  })[0];
  if (!plugin) throw new Error("Missing plugin fixture");
  const promise = connectMemberPlugin(plugin);
  await waitFor(() =>
    expect(popup.location.href).toBe("https://notes.example/oauth")
  );
  const body: { oauth_config_id: number; return_path: string } = JSON.parse(
    String(fetchSpy.mock.calls[0]?.[1]?.body)
  );
  expect(body.oauth_config_id).toBe(4);
  const returnUrl = new URL(body.return_path, window.location.origin);
  expect(returnUrl.pathname).toBe("/app/plugins/oauth/complete");
  expect(returnUrl.searchParams.get("pluginKind")).toBe("openapi");
  window.dispatchEvent(
    new MessageEvent("message", {
      origin: window.location.origin,
      source: popup,
      data: {
        type: "onyx:member-plugin-oauth-complete",
        attempt: returnUrl.searchParams.get("attempt"),
      },
    })
  );
  await promise;
  expect(fetchSpy.mock.calls.map(([input]) => input)).toEqual([
    "/api/oauth-config/initiate",
    "/api/tool",
    "/api/user-oauth-token/status",
  ]);
});
