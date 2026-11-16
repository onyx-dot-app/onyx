import {
  act,
  deferred,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { MCPConnectionStatus } from "@/lib/mcp/types";
import MemberPluginDetailModal from "@/sections/plugins/MemberPluginDetailModal";
import type { AppActionPoliciesView } from "@/lib/plugins/types";
import type { MemberPlugin } from "@/lib/plugins/member";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import {
  jsonResponse,
  memberServer,
  memberTool,
  storedMcpTool,
  memberApp,
  memberPluginMessages,
} from "@/sections/plugins/__tests__/memberPluginFixtures";

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => "/app/plugins",
  useSearchParams: () => new URLSearchParams(),
}));

let mockCraftEnabled: boolean | undefined = true;

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ onyx_craft_enabled: mockCraftEnabled }),
}));

beforeEach(() => {
  mockCraftEnabled = true;
  jest
    .spyOn(global, "fetch")
    .mockImplementation(async () => jsonResponse(approvalApp));
});

describe.each(["mcp", "openapi", "external-app"] as const)(
  "%s connection copy",
  (kind) => {
    test.each([
      { ownership: "session", text: "Ready to useUses your connected account" },
      { ownership: "workspace", text: "Ready to useWorkspace connection" },
      { ownership: "none", text: "Ready to useNo authentication required" },
      { ownership: "user", text: "Ready to useUses your connected account" },
    ] as const)(
      "shows only relevant $ownership copy",
      ({ ownership, text }) => {
        const connection = { kind: "connected", ownership } as const;
        show(
          kind === "mcp"
            ? {
                kind,
                server: memberServer(),
                tools: [storedMcpTool],
                connection,
              }
            : kind === "openapi"
              ? { kind, tool: memberTool(), connection }
              : { kind, app: memberApp({ authenticated: true }), connection }
        );
        expect(screen.getByRole("status").textContent).toBe(text);
      }
    );
  }
);

test("disabled Craft hides app-only metadata and launch action", () => {
  mockCraftEnabled = false;
  const requests = jest.spyOn(global, "fetch");
  show({
    kind: "external-app",
    app: memberApp({ authenticated: true }),
    connection: { kind: "connected", ownership: "user" },
  });
  expect(screen.queryByText("Craft")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "Open in Craft" })
  ).not.toBeInTheDocument();
  expect(requests).not.toHaveBeenCalled();
});

test.each([false, undefined])(
  "Craft entry points stay hidden when access is %s",
  (enabled) => {
    mockCraftEnabled = enabled;
    show({
      kind: "mcp",
      server: memberServer(),
      tools: [storedMcpTool],
      connection: { kind: "connected", ownership: "user" },
    });
    expect(
      screen.queryByRole("switch", { name: "Enable in Craft" })
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("switch", { name: "Enable in default Chat" })
    ).toBeVisible();
    expect(
      screen.queryByRole("link", { name: "Open in Craft" })
    ).not.toBeInTheDocument();
  }
);

function mockPolicyRequests() {
  return jest
    .spyOn(global, "fetch")
    .mockImplementation(async () =>
      jsonResponse({ ...approvalApp, actions: [] })
    );
}

function show(
  plugin: MemberPlugin,
  onDisconnected = jest.fn(),
  surface?: "all" | "craft",
  options: {
    initialTab?: "approvals";
    onClose?: () => void;
    beside?: ReactNode;
  } = {}
) {
  return render(
    <NextIntlClientProvider locale="en" messages={memberPluginMessages}>
      {options.beside}
      <MemberPluginDetailModal
        plugin={plugin}
        surface={surface}
        open
        initialTab={options.initialTab}
        onClose={options.onClose ?? jest.fn()}
        onConnect={jest.fn()}
        onDisconnected={onDisconnected}
      />
    </NextIntlClientProvider>
  );
}

afterEach(() => jest.restoreAllMocks());

test.each(["mcp", "openapi"] as const)(
  "%s keeps preference drafts after a failed Save and tab changes",
  async (kind) => {
    const pending = deferred<Response>();
    const requests = jest
      .spyOn(global, "fetch")
      .mockImplementation((input) =>
        String(input).includes("/action-policies/")
          ? Promise.resolve(jsonResponse(approvalApp))
          : pending.promise
      );
    show(
      kind === "mcp"
        ? {
            kind,
            server: memberServer(),
            tools: [storedMcpTool],
            connection: { kind: "connected", ownership: "user" },
          }
        : {
            kind,
            tool: memberTool(),
            connection: { kind: "connected", ownership: "none" },
          }
    );
    const user = setupUser();
    await user.click(
      screen.getByRole("switch", { name: "Enable in default Chat" })
    );
    expect(
      requests.mock.calls.filter(
        ([, init]) => init?.method && init.method !== "GET"
      )
    ).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    await act(async () =>
      pending.resolve(jsonResponse({ detail: "Save failed" }, 500))
    );
    await user.click(screen.getByRole("tab", { name: "Tools" }));
    await user.click(screen.getByRole("tab", { name: "Connection" }));
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(
      screen.getByRole("switch", { name: "Enable in default Chat" })
    ).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    expect(
      requests.mock.calls.filter(([, init]) => init?.method === "PATCH")
    ).toHaveLength(1);
  }
);

test("MCP connection details show the description instead of the server URL", () => {
  show({
    kind: "mcp",
    server: memberServer({
      description: "Find issues and projects in Linear.",
    }),
    tools: [storedMcpTool],
    connection: { kind: "connected", ownership: "user" },
  });
  expect(screen.getByRole("dialog")).toHaveAccessibleDescription(
    "Find issues and projects in Linear."
  );
  expect(
    screen.queryByText("https://mcp.linear.app/mcp")
  ).not.toBeInTheDocument();
  expect(screen.queryByText("Server URL")).not.toBeInTheDocument();
  expect(screen.getByText("Ready to use")).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("Ready to use");
});

test("MCP connection card reports needs sign-in when credentials are missing", () => {
  show({
    kind: "mcp",
    server: memberServer({
      connection_status: MCPConnectionStatus.NOT_CONNECTED,
    }),
    tools: [storedMcpTool],
    connection: { kind: "oauth" },
  });
  expect(screen.getByRole("status")).toHaveTextContent("Connect your account");
  expect(screen.queryByText("Connected")).not.toBeInTheDocument();
});

test.each(["https://api.linear.app", "https://[2606:4700::1111]:8443"])(
  "Craft app details show a description instead of service origin %s",
  (origin) => {
    const requests = mockPolicyRequests();
    show({
      kind: "external-app",
      app: memberApp({
        name: "Linear",
        app_type: "LINEAR",
        service_urls: [origin],
      }),
      connection: { kind: "connected", ownership: "user" },
    });
    expect(screen.queryByText(origin)).not.toBeInTheDocument();
    expect(screen.getByRole("dialog")).toHaveAccessibleDescription(
      memberPluginMessages.actions.memberPlugins.externalApp
        .craftOnlyDescription
    );
    expect(screen.getByRole("status")).toHaveTextContent("Ready to use");
    expect(
      requests.mock.calls.every(([input]) => !String(input).includes("/admin"))
    ).toBe(true);
  }
);

test.each([undefined, []])(
  "Craft app details omit missing service URLs (%s)",
  (service_urls) => {
    const requests = mockPolicyRequests();
    show({
      kind: "external-app",
      app: memberApp({ name: "Linear", app_type: "LINEAR", service_urls }),
      connection: { kind: "connected", ownership: "user" },
    });
    expect(screen.queryByText(/https?:\/\//)).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Ready to use");
    expect(
      requests.mock.calls.every(([input]) => !String(input).includes("/admin"))
    ).toBe(true);
  }
);

test("Craft App details share the connection card and Tools tab without admin data", () => {
  const requests = mockPolicyRequests();
  show({
    kind: "external-app",
    app: memberApp({ authenticated: true }),
    connection: { kind: "connected", ownership: "user" },
  });
  expect(screen.getByRole("status")).toHaveTextContent("Ready to use");
  expect(screen.queryByRole("term")).not.toBeInTheDocument();
  expect(
    screen.queryByText("Use your account in Craft.")
  ).not.toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Tools" })).toBeVisible();
  expect(screen.queryByRole("tab", { name: "Skills" })).not.toBeInTheDocument();
  expect(
    requests.mock.calls.every(([url]) =>
      String(url).includes("/action-policies/")
    )
  ).toBe(true);
});

test("Craft Apps needing authentication show connection guidance and Connect instead of launching Craft", () => {
  const requests = jest.spyOn(global, "fetch");
  show({
    kind: "external-app",
    app: memberApp({ authenticated: false }),
    connection: { kind: "oauth" },
  });
  expect(screen.getByRole("status")).toHaveTextContent("Connect your account");
  expect(screen.getByRole("button", { name: "Connect" })).toBeVisible();
  expect(
    screen.queryByRole("link", { name: "Open in Craft" })
  ).not.toBeInTheDocument();
  expect(
    requests.mock.calls.filter(
      ([, init]) => init?.method && init.method !== "GET"
    )
  ).toHaveLength(0);
});

test("personal external-app disconnect uses native credentials without fetching admin metadata", async () => {
  const disconnected = jest.fn();
  const requests = jest
    .spyOn(global, "fetch")
    .mockImplementation(async () => jsonResponse({}));
  show(
    {
      kind: "external-app",
      app: memberApp({ authenticated: true }),
      connection: { kind: "connected", ownership: "user" },
    },
    disconnected
  );
  const user = setupUser();
  requests.mockClear();
  await user.click(screen.getByRole("button", { name: "Disconnect" }));
  expect(
    requests.mock.calls.filter(
      ([, init]) => init?.method && init.method !== "GET"
    )
  ).toHaveLength(0);
  await user.click(screen.getByRole("button", { name: "Disconnect" }));
  await waitFor(() => expect(disconnected).toHaveBeenCalledTimes(1));
  expect(requests).toHaveBeenCalledWith("/api/build/apps/7/credentials", {
    method: "DELETE",
  });
});

test("Tools tab searches stored tools and expands full descriptions without live discovery", async () => {
  const requests = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(jsonResponse(approvalApp));
  const description = "Find issues in the projects you can access. ".repeat(20);
  show({
    kind: "mcp",
    server: memberServer(),
    tools: [{ ...storedMcpTool, description }],
    connection: { kind: "connected", ownership: "user" },
  });
  expect(screen.getByRole("tab", { name: "Connection" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  expect(screen.queryByText("Search issues")).not.toBeInTheDocument();
  await setupUser().click(screen.getByRole("tab", { name: "Tools" }));
  expect(screen.getByText("Search issues")).toBeVisible();
  expect(screen.getByText(description.trim())).toBeVisible();
  expect(screen.getByText("1 tool")).toBeVisible();
  expect(screen.getByRole("searchbox", { name: "Search tools" })).toBeVisible();
  expect(requests).toHaveBeenCalledTimes(1);
  expect(requests).toHaveBeenCalledWith("/api/action-policies/mcp_server/7");
  expect(screen.queryByText("Read")).not.toBeInTheDocument();
  expect(screen.queryByText("Ask first")).not.toBeInTheDocument();
});

test("canceling MCP disconnect returns to Connection without a request", async () => {
  const requests = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(jsonResponse(approvalApp));
  show({
    kind: "mcp",
    server: memberServer(),
    tools: [storedMcpTool],
    connection: { kind: "connected", ownership: "user" },
  });
  const user = setupUser();
  await user.click(screen.getByRole("tab", { name: "Tools" }));
  expect(
    screen.queryByRole("button", { name: "Disconnect" })
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("tab", { name: "Connection" }));
  await user.click(screen.getByRole("button", { name: "Disconnect" }));
  expect(screen.queryByRole("tab", { name: "Tools" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("tab", { name: "Connection" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  expect(screen.queryByText("Search issues")).not.toBeInTheDocument();
  expect(requests).toHaveBeenCalledTimes(1);
  expect(requests).toHaveBeenCalledWith("/api/action-policies/mcp_server/7");
});

test("empty MCP tools use the stored-catalog empty state", async () => {
  show({
    kind: "mcp",
    server: memberServer(),
    tools: [],
    connection: { kind: "connected", ownership: "workspace" },
  });
  await setupUser().click(screen.getByRole("tab", { name: "Tools" }));
  expect(
    screen.getByText("No visible tools are stored for this plugin.")
  ).toBeVisible();
  expect(screen.getByText("0 tools")).toBeVisible();
});

test("Craft MCP details do not imply an empty tool catalog when snapshots are unavailable", () => {
  const requests = jest.spyOn(global, "fetch");
  show(
    {
      kind: "mcp",
      server: memberServer(),
      tools: [],
      connection: { kind: "connected", ownership: "user" },
    },
    jest.fn(),
    "craft"
  );
  expect(screen.getByRole("tab", { name: "Tools" })).toBeVisible();
  expect(
    screen.queryByText("No visible tools are stored for this plugin.")
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "Open in Craft" })
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  expect(
    requests.mock.calls.filter(
      ([, init]) => init?.method && init.method !== "GET"
    )
  ).toHaveLength(0);
});

test.each(["workspace", "session", "none"] as const)(
  "%s connections have no personal disconnect action",
  (ownership) => {
    show({
      kind: "mcp",
      server: memberServer(),
      tools: [],
      connection: { kind: "connected", ownership },
    });
    expect(
      screen.queryByRole("button", { name: "Disconnect" })
    ).not.toBeInTheDocument();
  }
);

test("OpenAPI personal disconnect warns about the shared OAuth configuration before deleting the user token", async () => {
  const disconnected = jest.fn();
  const requests = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(jsonResponse({}));
  show(
    {
      kind: "openapi",
      tool: memberTool({ oauth_config_id: 9 }),
      connection: { kind: "connected", ownership: "user" },
    },
    disconnected
  );
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Disconnect" }));
  expect(
    screen.getByText(
      /all plugins and apps that use the same OAuth configuration/
    )
  ).toBeVisible();
  expect(
    requests.mock.calls.filter(
      ([, init]) => init?.method && init.method !== "GET"
    )
  ).toHaveLength(0);
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "Disconnect" }));
  await waitFor(() => expect(disconnected).toHaveBeenCalledTimes(1));
  expect(requests).toHaveBeenCalledWith("/api/oauth-config/9/token", {
    method: "DELETE",
  });
});

test("OpenAPI personal default is locked when the workspace disables main Chat", () => {
  show({
    kind: "openapi",
    tool: memberTool({ default_chat_enabled: false }),
    connection: { kind: "connected", ownership: "none" },
  });
  expect(screen.queryByText("Description")).not.toBeInTheDocument();
  const toggle = screen.getByRole("switch", {
    name: "Enable in default Chat",
  });
  expect(toggle).toHaveAttribute("aria-disabled", "true");
  expect(toggle).not.toBeChecked();
  expect(
    screen.getAllByText(
      "Your admin has disabled this plugin for Main Chat. Custom agents configured with this plugin may still use it."
    )
  ).toHaveLength(1);
  expect(
    screen.queryByRole("button", { name: "Use in Chat" })
  ).not.toBeInTheDocument();
});

test("OpenAPI personal default changes only on Save without changing workspace availability", async () => {
  const requests = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(jsonResponse({ enabled_in_chat: false }));
  show({
    kind: "openapi",
    tool: memberTool({
      default_chat_enabled: true,
      user_enabled_in_chat: true,
    }),
    connection: { kind: "connected", ownership: "none" },
  });
  const toggle = screen.getByRole("switch", {
    name: "Enable in default Chat",
  });
  expect(toggle).toBeChecked();
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  const user = setupUser();
  await user.click(toggle);
  await waitFor(() => expect(toggle).not.toBeChecked());
  expect(
    screen.queryByRole("button", { name: "Use in Chat" })
  ).not.toBeInTheDocument();
  expect(
    requests.mock.calls.filter(
      ([, init]) => init?.method && init.method !== "GET"
    )
  ).toHaveLength(0);
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(requests).toHaveBeenCalledTimes(1));
  expect(requests).toHaveBeenCalledWith(
    expect.stringMatching(/^\/api\/tool\/\d+\/preferences$/),
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ enabled_in_chat: false }),
    })
  );
});

test("OpenAPI details share MCP navigation and render schema endpoints, not the plugin as a tool", async () => {
  const requests = jest.spyOn(global, "fetch");
  show({
    kind: "openapi",
    tool: memberTool({
      definition: {
        servers: [{ url: "https://api.github.com" }],
        paths: {
          "/user": {
            get: { operationId: "getUser", summary: "Fetch the current user" },
          },
          "/user/repos": {
            post: { operationId: "createRepo", summary: "Create a repository" },
          },
        },
      },
    }),
    connection: { kind: "connected", ownership: "user" },
  });
  expect(screen.queryByText("https://api.github.com")).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Ready to use");
  expect(screen.getByRole("tab", { name: "Connection" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  expect(screen.queryByText("getUser")).not.toBeInTheDocument();
  await setupUser().click(screen.getByRole("tab", { name: "Tools" }));
  expect(screen.getByText("getUser")).toBeVisible();
  expect(screen.queryByText("GET")).not.toBeInTheDocument();
  expect(screen.getByText("Fetch the current user")).toBeVisible();
  expect(screen.getByText("createRepo")).toBeVisible();
  expect(screen.getByText("Create a repository")).toBeVisible();
  expect(screen.getByText("2 tools")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Disconnect" })
  ).not.toBeInTheDocument();
  expect(
    requests.mock.calls.filter(
      ([, init]) => init?.method && init.method !== "GET"
    )
  ).toHaveLength(0);
});

test("OpenAPI tools search matches name and description and reports no results", async () => {
  show({
    kind: "openapi",
    tool: memberTool({
      definition: {
        paths: {
          "/releases": {
            get: {
              operationId: "listReleases",
              summary: "List shipped versions",
            },
          },
          "/deployments": {
            post: {
              operationId: "createDeployment",
              summary: "Schedule a deployment",
            },
          },
        },
      },
    }),
    connection: { kind: "connected", ownership: "none" },
  });
  const user = setupUser();
  await user.click(screen.getByRole("tab", { name: "Tools" }));
  const search = screen.getByRole("searchbox", { name: "Search tools" });
  for (const query of ["createDeployment", "Schedule"]) {
    await user.clear(search);
    await user.type(search, query);
    expect(screen.getByText("createDeployment")).toBeVisible();
    expect(screen.queryByText("listReleases")).not.toBeInTheDocument();
    expect(screen.getByText("1 tool")).toBeVisible();
  }
  await user.clear(search);
  await user.type(search, "not-found");
  expect(screen.getByText("0 tools")).toBeVisible();
  expect(screen.getByText("No tools found")).toBeVisible();
  expect(screen.queryByRole("list")).not.toBeInTheDocument();
});

test("OpenAPI tools handle an empty schema without counting the plugin as an endpoint", async () => {
  show({
    kind: "openapi",
    tool: memberTool(),
    connection: { kind: "connected", ownership: "none" },
  });
  await setupUser().click(screen.getByRole("tab", { name: "Tools" }));
  expect(screen.getByText("0 tools")).toBeVisible();
  expect(
    screen.getByText("No visible tools are stored for this plugin.")
  ).toBeVisible();
});

test("OpenAPI missing credentials keep Connect and connection status without admin editors", () => {
  show({
    kind: "openapi",
    tool: memberTool({ oauth_config_id: 9 }),
    connection: { kind: "oauth" },
  });
  expect(screen.getByRole("status")).toHaveTextContent("Connect your account");
  expect(screen.getByRole("button", { name: "Connect" })).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Disconnect" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Edit authentication" })
  ).not.toBeInTheDocument();
});

test("main Chat disabled status prevents a Use in Chat action", () => {
  show({
    kind: "mcp",
    server: memberServer({
      default_chat_enabled: false,
      available_in_craft: true,
    }),
    tools: [storedMcpTool],
    connection: { kind: "connected", ownership: "user" },
  });
  expect(
    screen.queryByRole("button", { name: "Use in Chat" })
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("switch", { name: "Enable in default Chat" })
  ).toHaveAttribute("aria-disabled", "true");
});

test("personal main Chat default off hides Use in Chat and keeps account disconnect available", () => {
  const requests = jest.spyOn(global, "fetch");
  show({
    kind: "mcp",
    server: memberServer({ user_enabled_in_chat: false }),
    tools: [storedMcpTool],
    connection: { kind: "connected", ownership: "user" },
  });
  expect(
    screen.queryByRole("button", { name: "Use in Chat" })
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("switch", { name: "Enable in default Chat" })
  ).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Disconnect" })).toBeVisible();
  expect(
    requests.mock.calls.filter(
      ([, init]) => init?.method && init.method !== "GET"
    )
  ).toHaveLength(0);
});

test("MCP account disconnect confirms before deleting personal credentials", async () => {
  const disconnected = jest.fn();
  const requests = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(jsonResponse({}));
  show(
    {
      kind: "mcp",
      server: memberServer(),
      tools: [storedMcpTool],
      connection: { kind: "connected", ownership: "user" },
    },
    disconnected
  );
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Disconnect" }));
  expect(
    requests.mock.calls.filter(
      ([, init]) => init?.method && init.method !== "GET"
    )
  ).toHaveLength(0);
  expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Disconnect" }));
  await waitFor(() => expect(disconnected).toHaveBeenCalledTimes(1));
  expect(requests).toHaveBeenCalledWith("/api/mcp/user-credentials/7", {
    method: "DELETE",
  });
});

const approvalApp: AppActionPoliciesView = {
  gated_app_id: 42,
  kind: "mcp_server",
  target_id: 7,
  name: "Linear",
  users_can_manage_policies: true,
  actions: [
    {
      action_id: "send",
      normalised_name: "Send report",
      description: "",
      effective_policy: "ALWAYS",
      workspace_policy: "ASK",
      stored_policy: "ALWAYS",
      editable: true,
      lock_reason: null,
    },
    {
      action_id: "delete",
      normalised_name: "Delete report",
      description: "",
      effective_policy: "DENY",
      workspace_policy: "DENY",
      stored_policy: null,
      editable: false,
      lock_reason: "workspace_disabled",
    },
  ],
};
const approvalPlugin: MemberPlugin = {
  kind: "mcp",
  server: memberServer({ id: 7 }),
  tools: [],
  connection: { kind: "connected", ownership: "user" },
};

test("external app Tools shows approval settings without nested tabs", async () => {
  jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) =>
      jsonResponse(
        String(input).includes("action-policies")
          ? { ...approvalApp, kind: "external_app" }
          : { builtins: [], customs: [] }
      )
    );
  show({
    kind: "external-app",
    app: memberApp({ authenticated: true }),
    connection: { kind: "connected", ownership: "user" },
  });
  await setupUser().click(screen.getByRole("tab", { name: "Tools" }));
  expect(
    await screen.findByRole("group", { name: "Send report" })
  ).toBeVisible();
  expect(
    screen.queryByRole("tab", { name: "Available tools" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("tab", { name: "Approval settings" })
  ).not.toBeInTheDocument();
});

test.each([false, undefined])(
  "MCP approval settings do not need Craft when Craft access is %s",
  async (enabled) => {
    mockCraftEnabled = enabled;
    const requests = jest
      .spyOn(global, "fetch")
      .mockImplementation(async (input) =>
        jsonResponse(
          String(input).includes("/action-policies/") ? approvalApp : {}
        )
      );
    show({
      ...approvalPlugin,
      server: memberServer({ id: 7, available_in_craft: false }),
    });
    const user = setupUser();
    await user.click(screen.getByRole("tab", { name: "Tools" }));
    await user.click(screen.getByRole("tab", { name: "Approval settings" }));
    await user.click(
      within(
        await screen.findByRole("group", { name: "Send report" })
      ).getByRole("button", { name: "Ask" })
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(requests).toHaveBeenCalledWith(
        "/api/action-policies/mcp_server/7",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ action_policies: { send: "ASK" } }),
        })
      )
    );
  }
);

test("MCP approval settings stay hidden when the workspace manages them", async () => {
  const requests = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(jsonResponse(approvalApp));
  show(
    {
      ...approvalPlugin,
      tools: [storedMcpTool],
      server: memberServer({ id: 7, users_can_manage_policies: false }),
    },
    jest.fn(),
    "all",
    { initialTab: "approvals" }
  );
  await setupUser().click(screen.getByRole("tab", { name: "Tools" }));
  expect(screen.getByText("Search issues")).toBeVisible();
  expect(
    screen.queryByRole("tab", { name: "Approval settings" })
  ).not.toBeInTheDocument();
  expect(requests).not.toHaveBeenCalledWith(
    "/api/action-policies/mcp_server/7"
  );
});

test("external app approval settings need Craft", () => {
  mockCraftEnabled = false;
  const requests = jest.spyOn(global, "fetch");
  show({
    kind: "external-app",
    app: memberApp({ authenticated: true }),
    connection: { kind: "connected", ownership: "user" },
  });
  expect(screen.queryByRole("tab", { name: "Tools" })).not.toBeInTheDocument();
  expect(
    requests.mock.calls.some(([input]) =>
      String(input).includes("/action-policies/")
    )
  ).toBe(false);
});

test("approval loading retains the available tools until the editor is ready", async () => {
  const pending = deferred<Response>();
  const requests = jest.spyOn(global, "fetch").mockReturnValue(pending.promise);
  show({ ...approvalPlugin, tools: [storedMcpTool] });
  expect(requests).toHaveBeenCalledWith("/api/action-policies/mcp_server/7");
  expect(screen.getByRole("tab", { name: "Connection" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  const user = setupUser();
  await user.click(screen.getByRole("tab", { name: "Tools" }));
  await user.click(screen.getByRole("tab", { name: "Approval settings" }));
  expect(screen.getByText("Search issues")).toBeVisible();
  expect(
    screen.queryByText(memberPluginMessages.craft.actionPolicies.loading)
  ).not.toBeInTheDocument();
  await act(async () => pending.resolve(jsonResponse(approvalApp)));
  expect(
    await screen.findByRole("group", { name: "Send report" })
  ).toBeVisible();
  expect(
    screen.getByRole("tab", { name: "Approval settings" })
  ).toHaveAttribute("aria-selected", "true");
});

test("Craft Tools groups available actions and approval settings without writing on navigation", async () => {
  const requests = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(jsonResponse(approvalApp));
  show(approvalPlugin, jest.fn(), "craft");
  const user = setupUser();
  expect(
    screen.queryByRole("tab", { name: "Approval settings" })
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("tab", { name: "Tools" }));
  expect(screen.getByRole("tab", { name: "Available tools" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  expect(await screen.findByText("Send report")).toBeVisible();
  expect(screen.queryByText("Delete report")).not.toBeInTheDocument();
  await user.type(
    screen.getByRole("searchbox", {
      name: memberPluginMessages.actions.mcpTools.search,
    }),
    "missing"
  );
  expect(screen.queryByText("Send report")).not.toBeInTheDocument();
  await user.click(screen.getByRole("tab", { name: "Approval settings" }));
  expect(
    await screen.findByRole("group", { name: "Delete report" })
  ).toBeVisible();
  expect(
    requests.mock.calls.every(
      ([, init]) => !init?.method || init.method === "GET"
    )
  ).toBe(true);
});

test("available actions can retry a failed load and show an empty catalog", async () => {
  const requests = jest
    .spyOn(global, "fetch")
    .mockResolvedValueOnce(new Response("Unavailable", { status: 500 }))
    .mockResolvedValue(jsonResponse({ ...approvalApp, actions: [] }));
  show(approvalPlugin, jest.fn(), "craft");
  const user = setupUser();
  await user.click(screen.getByRole("tab", { name: "Tools" }));
  await user.click(
    await screen.findByRole("button", {
      name: memberPluginMessages.craft.actionPolicies.retry,
    })
  );
  expect(
    await screen.findByText("No visible tools are stored for this plugin.")
  ).toBeVisible();
  expect(requests).toHaveBeenCalledTimes(2);
});

test("loads a fresh approval snapshot and saves displayed choices including personal deny", async () => {
  const opening = deferred<Response>();
  const requests = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) =>
      String(input).endsWith("/action-policies/mcp_server/7")
        ? opening.promise
        : jsonResponse({})
    );
  const close = jest.fn();
  show(approvalPlugin, jest.fn(), "craft", {
    initialTab: "approvals",
    onClose: close,
  });
  expect(
    screen.queryByRole("group", { name: "Send report" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Try again" })
  ).not.toBeInTheDocument();
  await act(async () => opening.resolve(jsonResponse(approvalApp)));
  const user = setupUser();
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  for (const button of within(
    screen.getByRole("group", { name: "Delete report" })
  ).getAllByRole("button"))
    expect(button).toBeDisabled();
  await user.click(
    within(screen.getByRole("group", { name: "Send report" })).getByRole(
      "button",
      { name: "Blocked" }
    )
  );
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(close).toHaveBeenCalled());
  expect(requests).toHaveBeenCalledWith(
    "/api/action-policies/mcp_server/7",
    expect.objectContaining({
      body: JSON.stringify({ action_policies: { send: "DENY" } }),
    })
  );
});

test("retains approval drafts across tabs and confirms discarding on close", async () => {
  jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) =>
      jsonResponse(String(input).includes("action-policies") ? approvalApp : {})
    );
  const close = jest.fn();
  show(approvalPlugin, jest.fn(), "craft", {
    initialTab: "approvals",
    onClose: close,
  });
  const user = setupUser();
  await user.click(
    within(await screen.findByRole("group", { name: "Send report" })).getByRole(
      "button",
      { name: "Ask" }
    )
  );
  await user.click(screen.getByRole("tab", { name: "Connection" }));
  await user.click(screen.getByRole("tab", { name: /^Tools$/ }));
  await user.click(screen.getByRole("tab", { name: "Approval settings" }));
  expect(
    within(screen.getByRole("group", { name: "Send report" })).getByRole(
      "button",
      { name: "Ask" }
    )
  ).toHaveAttribute("aria-pressed", "true");
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(close).not.toHaveBeenCalled();
  expect(screen.getByText("Discard unsaved changes?")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Discard changes" }));
  expect(close).toHaveBeenCalled();
});

test("reset clears personal overrides only when saved", async () => {
  const requests = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) =>
      jsonResponse(String(input).endsWith("/mcp_server/7") ? approvalApp : {})
    );
  show(approvalPlugin, jest.fn(), "craft", { initialTab: "approvals" });
  const user = setupUser();
  await screen.findByRole("group", { name: "Send report" });
  await user.click(screen.getByRole("combobox", { name: "Set permissions" }));
  await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}{Enter}");
  expect(
    within(screen.getByRole("group", { name: "Send report" })).getByRole(
      "button",
      { name: "Ask" }
    )
  ).toHaveAttribute("aria-pressed", "true");
  expect(
    requests.mock.calls.filter(([, init]) => init?.method === "PUT")
  ).toHaveLength(0);
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(requests).toHaveBeenCalledWith(
      "/api/action-policies/mcp_server/7",
      expect.objectContaining({ body: JSON.stringify({ action_policies: {} }) })
    )
  );
});

test("a reopened detail owns its request while the previous request is pending", async () => {
  const earlier = deferred<Response>();
  const current = deferred<Response>();
  let loads = 0;
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    if (String(input).endsWith("/mcp_server/7"))
      return ++loads === 1 ? earlier.promise : current.promise;
    return jsonResponse({});
  });
  const first = show(approvalPlugin, jest.fn(), "craft", {
    initialTab: "approvals",
  });
  await waitFor(() => expect(loads).toBe(1));
  first.unmount();
  show(approvalPlugin, jest.fn(), "craft", { initialTab: "approvals" });
  await waitFor(() => expect(loads).toBe(2));
  await act(async () =>
    current.resolve(
      jsonResponse({
        ...approvalApp,
        actions: approvalApp.actions.map((item) =>
          item.action_id === "send"
            ? { ...item, effective_policy: "ASK", stored_policy: "ASK" }
            : item
        ),
      })
    )
  );
  expect(
    within(await screen.findByRole("group", { name: "Send report" })).getByRole(
      "button",
      { name: "Ask" }
    )
  ).toHaveAttribute("aria-pressed", "true");
  await act(async () => earlier.resolve(jsonResponse(approvalApp)));
  expect(
    within(screen.getByRole("group", { name: "Send report" })).getByRole(
      "button",
      { name: "Ask" }
    )
  ).toHaveAttribute("aria-pressed", "true");
});

test("keeps a failed save draft and blocks closing while the save is pending", async () => {
  const save = deferred<Response>();
  jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input, init) =>
      init?.method === "PUT" ? save.promise : jsonResponse(approvalApp)
    );
  const close = jest.fn();
  show(approvalPlugin, jest.fn(), "craft", {
    initialTab: "approvals",
    onClose: close,
  });
  const user = setupUser();
  await user.click(
    within(await screen.findByRole("group", { name: "Send report" })).getByRole(
      "button",
      { name: "Ask" }
    )
  );
  await user.click(screen.getByRole("button", { name: "Save" }));
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(close).not.toHaveBeenCalled();
  for (const button of within(
    screen.getByRole("group", { name: "Send report" })
  ).getAllByRole("button"))
    expect(button).toBeDisabled();
  await user.keyboard("{Escape}");
  expect(close).not.toHaveBeenCalled();
  await act(async () =>
    save.resolve(jsonResponse({ detail: "Save failed" }, 500))
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("Save failed");
  expect(
    within(screen.getByRole("group", { name: "Send report" })).getByRole(
      "button",
      { name: "Ask" }
    )
  ).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
});

test("workspace-managed approvals remain visible but cannot be saved", async () => {
  jest.spyOn(global, "fetch").mockResolvedValue(
    jsonResponse({
      ...approvalApp,
      users_can_manage_policies: false,
      actions: approvalApp.actions.map((action) => ({
        ...action,
        editable: false,
        lock_reason: "workspace_managed",
      })),
    })
  );
  show(approvalPlugin, jest.fn(), "craft", { initialTab: "approvals" });
  for (const button of within(
    await screen.findByRole("group", { name: "Send report" })
  ).getAllByRole("button"))
    expect(button).toBeDisabled();
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
});

test.each(["mcp", "openapi"] as const)(
  "%s Cancel discards preference drafts without a request",
  async (kind) => {
    const requests = jest.spyOn(global, "fetch");
    const close = jest.fn();
    show(
      kind === "mcp"
        ? {
            kind,
            server: memberServer(),
            tools: [storedMcpTool],
            connection: { kind: "connected", ownership: "user" },
          }
        : {
            kind,
            tool: memberTool(),
            connection: { kind: "connected", ownership: "none" },
          },
      jest.fn(),
      "all",
      { onClose: close }
    );
    const user = setupUser();
    await user.click(
      screen.getByRole("switch", { name: "Enable in default Chat" })
    );
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(close).not.toHaveBeenCalled();
    expect(screen.getByText("Discard unsaved changes?")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(close).toHaveBeenCalledTimes(1);
    expect(
      requests.mock.calls.filter(
        ([, init]) => init?.method && init.method !== "GET"
      )
    ).toHaveLength(0);
  }
);

test("retry saves only approvals after preference changes succeeded", async () => {
  let policyAttempts = 0;
  const requests = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (_input, init) => {
      if (init?.method === "PATCH")
        return jsonResponse({
          enabled_in_chat: false,
          enabled_in_craft: false,
        });
      if (init?.method === "PUT") {
        policyAttempts += 1;
        return policyAttempts === 1
          ? jsonResponse({ detail: "Save failed" }, 500)
          : jsonResponse({});
      }
      return jsonResponse(approvalApp);
    });
  const close = jest.fn();
  show(approvalPlugin, jest.fn(), "all", { onClose: close });
  const user = setupUser();
  await user.click(
    screen.getByRole("switch", { name: "Enable in default Chat" })
  );
  await user.click(screen.getByRole("switch", { name: "Enable in Craft" }));
  await user.click(screen.getByRole("tab", { name: "Tools" }));
  await user.click(screen.getByRole("tab", { name: "Approval settings" }));
  await user.click(
    within(await screen.findByRole("group", { name: "Send report" })).getByRole(
      "button",
      { name: "Ask" }
    )
  );
  expect(requests.mock.calls.filter(([, init]) => init?.method)).toHaveLength(
    0
  );
  await user.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Save failed");
  expect(close).not.toHaveBeenCalled();
  expect(requests).toHaveBeenCalledWith(
    "/api/mcp/server/7/preferences",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ enabled_in_chat: false, enabled_in_craft: false }),
    })
  );
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(close).toHaveBeenCalledTimes(1));
  expect(
    requests.mock.calls.filter(([, init]) => init?.method === "PATCH")
  ).toHaveLength(1);
  expect(
    requests.mock.calls.filter(([, init]) => init?.method === "PUT")
  ).toHaveLength(2);
});
