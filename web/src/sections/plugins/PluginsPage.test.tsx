import { MCPConnectionStatus } from "@/lib/mcp/types";
import type { ComponentProps } from "react";
import {
  render,
  screen,
  setupUser,
  waitFor,
  deferred,
  within,
  act,
} from "@tests/setup/test-utils";
import PluginsPage from "@/sections/plugins/PluginsPage";
import type MCPPluginSetupModal from "@/sections/actions/modals/MCPPluginSetupModal";
import type OpenAPIPluginCreateModal from "@/sections/plugins/OpenAPIPluginCreateModal";
import { MCPServerStatus, type MCPServer } from "@/lib/mcp/types";
import type { ToolSnapshot } from "@/lib/tools/types";
import { SUGGESTED_MCP_PLUGINS } from "@/lib/plugins/catalog";
import messages from "@/i18n/messages/en.json";
import type { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";

const copy = messages.actions.plugins;
const mockPush = jest.fn();
const mockReplace = jest.fn();
const mockRouter = { push: mockPush, replace: mockReplace };
let mockSearchParams = new URLSearchParams();
let mockCanCreate = true;
let mockFullAdmin = false;
let mockScopedManager = false;
let mockCraftAvailable = true;

jest.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  usePathname: () => "/admin/plugins",
  useSearchParams: () => mockSearchParams,
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: (permission: string) => ({
    isGlobalHolder: permission === "admin" ? mockFullAdmin : mockCanCreate,
    isScopedManager: permission !== "admin" && mockScopedManager,
  }),
}));
jest.mock("@/sections/actions/modals/MCPPluginSetupModal", () => ({
  __esModule: true,
  default: function MockMCPModal(
    props: ComponentProps<typeof MCPPluginSetupModal>
  ) {
    return props.open ? (
      <div role="dialog" aria-label="MCP setup">
        <input
          aria-label="Server URL"
          readOnly
          value={props.initialUrl ?? ""}
        />
        <input
          aria-label="Server name"
          readOnly
          value={props.initialName ?? ""}
        />
        <button onClick={() => props.onCompleted(mockServer)}>
          Complete setup
        </button>
        <button onClick={props.onClose}>Close</button>
      </div>
    ) : null;
  },
}));
jest.mock("@/sections/plugins/OpenAPIPluginCreateModal", () => ({
  __esModule: true,
  default: function MockOpenAPIModal(
    props: ComponentProps<typeof OpenAPIPluginCreateModal>
  ) {
    return props.open ? (
      <div role="dialog" aria-label="OpenAPI setup">
        <button onClick={() => props.onCreated(7)}>Create action</button>
      </div>
    ) : null;
  },
}));

const mockServer: MCPServer = {
  connection_status: null,
  id: 7,
  name: "Workspace MCP",
  description: "Search support tickets",
  server_url: "https://workspace.example.com/mcp",
  owner: "admin@example.com",
  status: MCPServerStatus.CONNECTED,
  is_public: true,
  groups: [],
  users: [],
  tool_count: 3,
  available_in_craft: false,
  default_chat_enabled: true,
  permissions: { edit: true, authenticate: true },
};
const tool: ToolSnapshot = {
  id: 7,
  name: "Reports API",
  display_name: "Reports API",
  description: "Read weekly reports",
  definition: {},
  custom_headers: [],
  in_code_tool_id: null,
  passthrough_auth: false,
  enabled: true,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: false,
  default_chat_enabled: true,
  permissions: {},
};
const externalApp: ExternalAppAdminResponse = {
  id: 7,
  name: "Workspace service",
  app_type: "CUSTOM",
  enabled: true,
  upstream_url_patterns: ["https://service.example.com/*"],
  auth_template: {},
  organization_credentials: {},
  credential_placeholder_keys: [],
  actions: [],
  associated_skills: [],
  is_onyx_managed: false,
  users_can_manage_policies: true,
};

function mockNetwork({
  mcpStatus = 200,
  openapiStatus = 200,
  empty = false,
  servers = [mockServer],
  tools = [tool],
  apps = [externalApp],
}: {
  mcpStatus?: number;
  openapiStatus?: number;
  empty?: boolean;
  servers?: MCPServer[];
  tools?: ToolSnapshot[];
  apps?: ExternalAppAdminResponse[];
} = {}) {
  return jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/settings" || url === "/api/enterprise-settings")
      return new Response(
        JSON.stringify({ onyx_craft_available: mockCraftAvailable })
      );
    if (url === "/api/admin/default-assistant/configuration")
      return new Response(
        JSON.stringify({ tool_ids: [tool.id], is_default_persona: true })
      );
    if (url === "/api/admin/mcp/server/7/tools/snapshots?source=db")
      return new Response(JSON.stringify([tool]));
    if (url === "/api/build/admin/apps")
      return new Response(JSON.stringify(empty ? [] : apps));
    if (url === "/api/build/admin/apps/built-in/options")
      return new Response(JSON.stringify([]));
    if (url === "/api/admin/mcp/servers")
      return new Response(
        JSON.stringify(
          mcpStatus === 200
            ? { mcp_servers: empty ? [] : servers }
            : { detail: "MCP unavailable" }
        ),
        { status: mcpStatus }
      );
    if (url === "/api/tool/openapi")
      return new Response(
        JSON.stringify(
          openapiStatus === 200
            ? empty
              ? []
              : tools
            : { detail: "OpenAPI unavailable" }
        ),
        { status: openapiStatus }
      );
    throw new Error(`Unexpected request: ${url}`);
  });
}

beforeEach(() => {
  mockPush.mockClear();
  mockReplace.mockClear();
  mockSearchParams = new URLSearchParams();
  mockCanCreate = true;
  mockFullAdmin = false;
  mockScopedManager = false;
  mockCraftAvailable = true;
});
afterEach(() => jest.restoreAllMocks());

test("Craft-disabled admins see only Chat plugins and never request Craft apps", async () => {
  mockFullAdmin = true;
  mockCraftAvailable = false;
  mockSearchParams = new URLSearchParams("add=external-app");
  const network = mockNetwork();
  render(<PluginsPage />);
  await screen.findByRole("link", { name: "Manage Workspace MCP" });
  expect(screen.getByRole("link", { name: "View Reports API" })).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Craft Apps" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "Manage Workspace service" })
  ).not.toBeInTheDocument();
  await setupUser().click(screen.getByRole("button", { name: copy.add.label }));
  expect(
    screen.queryByRole("menuitem", { name: "Craft Apps" })
  ).not.toBeInTheDocument();
  expect(
    network.mock.calls.some(([url]) => String(url).startsWith("/api/build/"))
  ).toBe(false);
});

test("hides installed endpoints in the MCP catalog regardless of their display name or trailing slash", async () => {
  mockNetwork({
    servers: [
      {
        ...mockServer,
        name: "Renamed workspace",
        server_url: "https://mcp.linear.app/mcp/",
      },
    ],
  });
  render(<PluginsPage />);
  await screen.findByRole("link", { name: /Renamed workspace/ });
  await setupUser().click(screen.getByRole("button", { name: copy.add.label }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await setupUser().click(
    screen.getByRole("menuitem", { name: copy.kind.mcp })
  );
  expect(
    screen.queryByRole("button", { name: "Add Linear" })
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add Sentry" })).toBeVisible();
});

test("refreshes persisted incomplete servers when MCP setup is dismissed", async () => {
  let mcpReads = 0;
  mockSearchParams = new URLSearchParams("add=mcp");
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    if (String(input) === "/api/admin/mcp/servers") {
      mcpReads += 1;
      return new Response(
        JSON.stringify({
          mcp_servers:
            mcpReads === 1
              ? []
              : [{ ...mockServer, status: MCPServerStatus.DISCONNECTED }],
        })
      );
    }
    if (String(input) === "/api/tool/openapi")
      return new Response(JSON.stringify([]));
    throw new Error(`Unexpected request: ${String(input)}`);
  });
  render(<PluginsPage />);
  await screen.findByText(copy.state.empty.title);
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(
    await screen.findByRole("link", { name: "Manage Workspace MCP" })
  ).toHaveAttribute("href", "/admin/plugins/mcp/7");
  expect(
    screen.queryByRole("dialog", { name: "MCP setup" })
  ).not.toBeInTheDocument();
  expect(mcpReads).toBe(2);
});

test("lists native records with colliding IDs and permission-aware detail links", async () => {
  const network = mockNetwork();
  render(<PluginsPage />);
  expect(
    await screen.findByRole("link", { name: "Manage Workspace MCP" })
  ).toHaveAttribute("href", "/admin/plugins/mcp/7");
  expect(
    await screen.findByRole("link", { name: "View Reports API" })
  ).toHaveAttribute("href", "/admin/plugins/openapi/7");
  expect(network.mock.calls.map(([url]) => String(url)).sort()).toEqual([
    "/api/admin/mcp/servers",
    "/api/enterprise-settings",
    "/api/settings",
    "/api/tool/openapi",
  ]);
  const status = within(
    screen.getByRole("group", { name: mockServer.name })
  ).getByRole("button", { name: "Chat on" });
  expect(status).toBeVisible();
  expect(
    within(screen.getByRole("group", { name: tool.name })).getByRole("button", {
      name: "Chat on",
    })
  ).toBeVisible();
  await setupUser().hover(status);
  const tooltip = await screen.findByRole("tooltip");
  expect(within(tooltip).getByText("Main Chat")).toBeVisible();
  expect(within(tooltip).getByText("Craft")).toBeVisible();
  expect(within(tooltip).getByText("On")).toBeVisible();
  expect(within(tooltip).getByText("Off")).toBeVisible();
});

test("includes external apps with colliding IDs only for full admins", async () => {
  mockFullAdmin = true;
  mockNetwork();
  render(<PluginsPage />);
  expect(
    await screen.findByRole("link", { name: "Manage Workspace service" })
  ).toHaveAttribute("href", "/admin/plugins/external-app/7");
  expect(
    screen.getByRole("link", { name: "Manage Workspace MCP" })
  ).toHaveAttribute("href", "/admin/plugins/mcp/7");
  expect(
    screen.getByRole("link", { name: "View Reports API" })
  ).toHaveAttribute("href", "/admin/plugins/openapi/7");
  expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  const filters = screen.getByRole("group", { name: "Plugin type" });
  const user = setupUser();
  await user.click(within(filters).getByRole("button", { name: "MCP" }));
  expect(
    screen.getByRole("link", { name: "Manage Workspace MCP" })
  ).toBeVisible();
  expect(
    screen.queryByRole("link", { name: "View Reports API" })
  ).not.toBeInTheDocument();
  await user.click(within(filters).getByRole("button", { name: "OpenAPI" }));
  expect(screen.getByRole("link", { name: "View Reports API" })).toBeVisible();
  expect(
    screen.queryByRole("link", { name: "Manage Workspace MCP" })
  ).not.toBeInTheDocument();
  await user.click(within(filters).getByRole("button", { name: "Craft Apps" }));
  expect(
    screen.getByRole("link", { name: "Manage Workspace service" })
  ).toBeVisible();
  expect(
    screen.queryByRole("link", { name: "View Reports API" })
  ).not.toBeInTheDocument();
  await user.click(within(filters).getByRole("button", { name: "All" }));
  expect(screen.getByRole("link", { name: "View Reports API" })).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Add Sentry" })
  ).not.toBeInTheDocument();
});

test("never requests external admin records or provider options for scoped action managers", async () => {
  mockCanCreate = false;
  mockScopedManager = true;
  const network = mockNetwork();
  render(<PluginsPage />);
  await screen.findByRole("link", { name: "Manage Workspace MCP" });
  expect(
    screen.queryByRole("button", { name: "Craft Apps" })
  ).not.toBeInTheDocument();
  await setupUser().click(screen.getByRole("button", { name: copy.add.label }));
  expect(
    screen.queryByRole("menuitem", { name: copy.kind["external-app"] })
  ).not.toBeInTheDocument();
  await setupUser().click(
    screen.getByRole("menuitem", { name: copy.kind.mcp })
  );
  expect(screen.getByRole("button", { name: "Add Sentry" })).toBeVisible();
  expect(
    network.mock.calls.some(([url]) =>
      String(url).startsWith("/api/build/admin/apps")
    )
  ).toBe(false);
});

test("keeps the main Chat indicator off when only Craft is enabled", async () => {
  mockNetwork({
    servers: [
      { ...mockServer, default_chat_enabled: false, available_in_craft: true },
    ],
  });
  render(<PluginsPage />);
  const status = await screen.findByRole("button", { name: "Chat off" });
  await setupUser().hover(status);
  const tooltip = await screen.findByRole("tooltip");
  expect(within(tooltip).getByText("Craft")).toBeVisible();
  expect(within(tooltip).getByText("On")).toBeVisible();
});

test("the status circle has no availability menu", async () => {
  mockFullAdmin = true;
  mockNetwork({
    servers: [
      { ...mockServer, default_chat_enabled: true, available_in_craft: true },
    ],
  });
  render(<PluginsPage />);
  const status = within(
    await screen.findByRole("group", { name: mockServer.name })
  ).getByRole("button", { name: "Chat on" });
  expect(status).not.toHaveAttribute("aria-haspopup");
  await setupUser().click(status);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(
    within(screen.getByRole("group", { name: mockServer.name })).queryByRole(
      "button",
      { name: /for workspace|workspace availability/ }
    )
  ).not.toBeInTheDocument();
});

test.each([true, false])(
  "admin status shows workspace Chat enabled=%s regardless of personal authentication",
  async (enabled) => {
    mockNetwork({
      servers: [
        {
          ...mockServer,
          status: MCPServerStatus.AWAITING_AUTH,
          connection_status: MCPConnectionStatus.NOT_CONNECTED,
          default_chat_enabled: enabled,
          available_in_craft: true,
        },
      ],
    });
    render(<PluginsPage />);
    const status = within(
      await screen.findByRole("group", { name: mockServer.name })
    ).getByRole("button", {
      name: enabled ? "Chat on" : "Chat off",
    });
    expect(
      screen.queryByRole("button", { name: "Needs sign-in" })
    ).not.toBeInTheDocument();
    await setupUser().hover(status);
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("Main Chat");
    expect(tooltip).toHaveTextContent(enabled ? "On" : "Off");
    expect(tooltip).not.toHaveTextContent("Needs sign-in");
  }
);

test("filters by description and URL and clears a search without losing either resource", async () => {
  mockNetwork();
  render(<PluginsPage />);
  await screen.findByRole("link", { name: "Manage Workspace MCP" });
  const user = setupUser();
  const search = screen.getByRole("textbox", { name: copy.search.placeholder });
  await user.type(search, "weekly");
  expect(screen.getByRole("link", { name: "View Reports API" })).toBeVisible();
  expect(
    screen.queryByRole("link", { name: "Manage Workspace MCP" })
  ).not.toBeInTheDocument();
  await user.clear(search);
  await user.type(search, "workspace.example.com");
  expect(
    screen.getByRole("link", { name: "Manage Workspace MCP" })
  ).toBeVisible();
  await user.clear(search);
  await user.type(search, "missing");
  expect(screen.getByText(copy.state.noResults.title)).toBeVisible();
  await user.click(
    screen.getByRole("button", { name: copy.state.noResults.clear.label })
  );
  expect(screen.getByRole("link", { name: "View Reports API" })).toBeVisible();
  expect(
    screen.getByRole("link", { name: "Manage Workspace MCP" })
  ).toBeVisible();
});

test.each([
  {
    mcpStatus: 503,
    openapiStatus: 200,
    error: copy.state.mcpError,
    successfulLink: "View Reports API",
    retryUrl: "/api/admin/mcp/servers",
  },
  {
    mcpStatus: 200,
    openapiStatus: 503,
    error: copy.state.openapiError,
    successfulLink: "Manage Workspace MCP",
    retryUrl: "/api/tool/openapi",
  },
])(
  "keeps the successful list visible when $retryUrl fails and retries only that list",
  async ({ mcpStatus, openapiStatus, error, successfulLink, retryUrl }) => {
    const network = mockNetwork({ mcpStatus, openapiStatus });
    render(<PluginsPage />);
    expect(
      await screen.findByRole("link", { name: successfulLink })
    ).toBeVisible();
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(error)).toBeVisible();
    await setupUser().click(
      within(alert).getByRole("button", { name: copy.state.retry.label })
    );
    await waitFor(() =>
      expect(
        network.mock.calls.filter(([url]) => url === retryUrl)
      ).toHaveLength(2)
    );
    expect(screen.queryByText(copy.state.empty.title)).not.toBeInTheDocument();
  }
);

test("shows an available list while the other list is still loading", async () => {
  const pending = deferred<Response>();
  jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) =>
      String(input) === "/api/admin/mcp/servers"
        ? pending.promise
        : new Response(JSON.stringify([tool]))
    );
  render(<PluginsPage />);
  expect(
    await screen.findByRole("link", { name: "View Reports API" })
  ).toBeVisible();
  expect(
    screen.getByRole("status", { name: copy.state.loading })
  ).toBeVisible();
  pending.resolve(new Response(JSON.stringify({ mcp_servers: [mockServer] })));
  expect(
    await screen.findByRole("link", { name: "Manage Workspace MCP" })
  ).toBeVisible();
});

test("leads an empty installation through the type dropdown to suggested MCP plugins", async () => {
  mockNetwork({ empty: true });
  render(<PluginsPage />);
  expect(await screen.findByText(copy.state.empty.title)).toBeVisible();
  await setupUser().click(
    screen.getAllByRole("button", { name: copy.add.label }).at(-1) ??
      screen.getByRole("button", { name: copy.add.label })
  );
  await setupUser().click(
    screen.getByRole("menuitem", { name: copy.kind.mcp })
  );
  expect(screen.getByRole("button", { name: "Add Linear" })).toBeVisible();
  expect(screen.getByText(copy.catalog.atlassian.summary)).toBeVisible();
});

test("full admins can open an app-only catalog from Add", async () => {
  mockFullAdmin = true;
  const network = mockNetwork();
  render(<PluginsPage />);
  await screen.findByRole("link", { name: "Manage Workspace service" });
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: copy.add.label }));
  expect(screen.getAllByRole("menuitem")).toHaveLength(3);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(
    network.mock.calls.some(([url]) => String(url).endsWith("built-in/options"))
  ).toBe(false);
  await user.click(
    screen.getByRole("menuitem", { name: copy.kind["external-app"] })
  );
  expect(await screen.findByRole("dialog")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Add Sentry" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: copy.add.mcp })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: copy.add.openapi })
  ).not.toBeInTheDocument();
});

test.each(SUGGESTED_MCP_PLUGINS)(
  "seeds the shared MCP modal from $name without probing on directory load",
  async ({ name, serverUrl }) => {
    const network = mockNetwork();
    render(<PluginsPage />);
    await setupUser().click(
      screen.getByRole("button", { name: copy.add.label })
    );
    await setupUser().click(
      screen.getByRole("menuitem", { name: copy.kind.mcp })
    );
    await setupUser().click(
      screen.getByRole("button", { name: `Add ${name}` })
    );
    expect(screen.getByRole("textbox", { name: "Server URL" })).toHaveValue(
      serverUrl
    );
    expect(screen.getByRole("textbox", { name: "Server name" })).toHaveValue(
      name
    );
    expect(network.mock.calls.map(([url]) => String(url)).sort()).toEqual([
      "/api/admin/mcp/servers",
      "/api/enterprise-settings",
      "/api/settings",
      "/api/tool/openapi",
    ]);
  }
);

test("opens custom MCP and routes a completed native server to its canonical detail", async () => {
  mockNetwork();
  render(<PluginsPage />);
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: copy.add.label }));
  await user.click(screen.getByRole("menuitem", { name: copy.kind.mcp }));
  await user.click(screen.getByRole("button", { name: copy.add.mcp }));
  expect(screen.getByRole("textbox", { name: "Server URL" })).toHaveValue("");
  await user.click(screen.getByRole("button", { name: "Complete setup" }));
  expect(mockPush).toHaveBeenCalledWith("/admin/plugins/mcp/7");
});

test("opens OpenAPI creation and configures authentication on its canonical detail", async () => {
  mockNetwork();
  render(<PluginsPage />);
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: copy.add.label }));
  await user.click(screen.getByRole("menuitem", { name: copy.kind.openapi }));
  await user.click(screen.getByRole("button", { name: "Create action" }));
  expect(mockPush).toHaveBeenCalledWith("/admin/plugins/openapi/7");
});

test("a creation deep link replaces an open catalog instead of opening a second dialog", async () => {
  mockNetwork();
  const view = render(<PluginsPage />);
  await screen.findByRole("link", { name: "Manage Workspace MCP" });
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: copy.add.label }));
  await user.click(screen.getByRole("menuitem", { name: copy.kind.mcp }));
  expect(screen.getByRole("dialog", { name: copy.kind.mcp })).toBeVisible();
  mockSearchParams = new URLSearchParams({ add: "openapi" });
  view.rerender(<PluginsPage />);
  expect(
    await screen.findByRole("dialog", { name: "OpenAPI setup" })
  ).toBeVisible();
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
});

test("consumes a creation deep link and preserves unrelated query parameters", async () => {
  mockNetwork();
  mockSearchParams = new URLSearchParams(
    "add=mcp&source=chat&filter=one&filter=two"
  );
  const { rerender } = render(<PluginsPage />);
  expect(screen.getByRole("dialog", { name: "MCP setup" })).toBeVisible();
  expect(mockReplace).toHaveBeenCalledWith(
    "/admin/plugins?source=chat&filter=one&filter=two"
  );
  rerender(<PluginsPage />);
  expect(mockReplace).toHaveBeenCalledTimes(1);
  await setupUser().click(screen.getByRole("button", { name: "Close" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("keeps creation controls absent without action-management authority", async () => {
  mockNetwork();
  mockCanCreate = false;
  mockSearchParams = new URLSearchParams("add=mcp");
  await act(async () => {
    render(<PluginsPage />);
  });
  for (const plugin of SUGGESTED_MCP_PLUGINS) {
    expect(screen.queryByText(plugin.name)).not.toBeInTheDocument();
  }
  expect(
    screen.queryByRole("button", { name: copy.add.label })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Add Linear" })
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("orders cards by availability, then type, then name", async () => {
  mockFullAdmin = true;
  mockNetwork({
    servers: [
      {
        ...mockServer,
        id: 1,
        name: "MCP disabled",
        default_chat_enabled: false,
      },
      {
        ...mockServer,
        id: 2,
        name: "MCP Craft only",
        default_chat_enabled: false,
        available_in_craft: true,
      },
      { ...mockServer, id: 3, name: "MCP Chat active" },
    ],
    tools: [
      { ...tool, id: 1, name: "OpenAPI disabled", default_chat_enabled: false },
      { ...tool, id: 2, name: "OpenAPI active" },
    ],
    apps: [
      { ...externalApp, id: 1, name: "App disabled", enabled: false },
      { ...externalApp, id: 2, name: "App active" },
    ],
  });
  render(<PluginsPage />);
  await waitFor(() =>
    expect(
      screen
        .getAllByRole("group", { name: /^(MCP|OpenAPI|App) / })
        .map((card) => card.getAttribute("aria-label"))
    ).toEqual([
      "MCP Chat active",
      "MCP Craft only",
      "OpenAPI active",
      "App active",
      "MCP disabled",
      "OpenAPI disabled",
      "App disabled",
    ])
  );
});

test.each([true, false])(
  "OpenAPI indicator reflects default Chat selection=%s",
  async (defaultChatEnabled) => {
    mockNetwork({
      servers: [],
      apps: [],
      tools: [
        { ...tool, enabled: true, default_chat_enabled: defaultChatEnabled },
      ],
    });
    render(<PluginsPage />);
    const status = await screen.findByRole("button", {
      name: defaultChatEnabled ? "Chat on" : "Chat off",
    });
    await setupUser().hover(status);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Main Chat");
    expect(screen.getByRole("tooltip")).toHaveTextContent(
      defaultChatEnabled ? "On" : "Off"
    );
    expect(
      screen.getByRole("link", { name: "View Reports API" })
    ).toBeVisible();
  }
);
