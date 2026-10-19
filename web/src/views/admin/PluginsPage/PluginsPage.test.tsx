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
import PluginsPage from "@/views/admin/PluginsPage";
import type MCPPluginSetupModal from "@/views/admin/PluginsPage/components/mcp/MCPPluginSetupModal";
import type OpenAPIPluginModal from "@/views/admin/PluginsPage/OpenAPIPluginModal";
import type MCPPluginDetailPage from "@/views/admin/PluginsPage/MCPPluginDetailPage";
import type ExternalAppPluginDetailPage from "@/views/admin/PluginsPage/ExternalAppPluginDetailPage";
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
jest.mock(
  "@/views/admin/PluginsPage/components/mcp/MCPPluginSetupModal",
  () => ({
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
  })
);
/** An opened plugin's modal: its name, the parameters it got, and Close. */
function MockOpenedModal({
  name,
  params,
  onClose,
}: {
  name: string;
  params?: URLSearchParams;
  onClose?: () => void;
}) {
  return (
    <div role="dialog" aria-label={name}>
      <output aria-label="Opened with">{params?.toString() ?? ""}</output>
      <button onClick={onClose}>Close</button>
    </div>
  );
}
jest.mock("@/views/admin/PluginsPage/OpenAPIPluginModal", () => ({
  __esModule: true,
  default: function MockOpenAPIModal(
    props: ComponentProps<typeof OpenAPIPluginModal>
  ) {
    if (props.toolId !== undefined)
      return (
        <MockOpenedModal
          name={`OpenAPI plugin ${props.toolId}`}
          params={props.params}
          onClose={props.onClose}
        />
      );
    return (
      <div role="dialog" aria-label="OpenAPI setup">
        <button onClick={() => props.onCreated?.(7)}>Create action</button>
      </div>
    );
  },
}));
jest.mock("@/views/admin/PluginsPage/MCPPluginDetailPage", () => ({
  __esModule: true,
  default: function MockMCPDetail(
    props: ComponentProps<typeof MCPPluginDetailPage>
  ) {
    return (
      <MockOpenedModal
        name={`MCP plugin ${props.serverId}`}
        params={props.params}
        onClose={props.onClose}
      />
    );
  },
}));
jest.mock("@/views/admin/PluginsPage/ExternalAppPluginDetailPage", () => ({
  __esModule: true,
  default: function MockExternalAppDetail(
    props: ComponentProps<typeof ExternalAppPluginDetailPage>
  ) {
    return (
      <MockOpenedModal
        name={`App plugin ${props.appId}`}
        onClose={props.onClose}
      />
    );
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
};

function mockNetwork({
  mcpStatus = 200,
  openapiStatus = 200,
  empty = false,
  servers = [mockServer],
}: {
  mcpStatus?: number;
  openapiStatus?: number;
  empty?: boolean;
  servers?: MCPServer[];
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
      return new Response(JSON.stringify(empty ? [] : [externalApp]));
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
              : [tool]
            : { detail: "OpenAPI unavailable" }
        ),
        { status: openapiStatus }
      );
    throw new Error(`Unexpected request: ${url}`);
  });
}

/** A plugin card: a labelled `<div>`, so its own buttons never match. */
function card(name: string) {
  return screen.getByLabelText(name, { selector: "div" });
}
function findCard(name: string) {
  return screen.findByLabelText(name, { selector: "div" });
}
function queryCard(name: string) {
  return screen.queryByLabelText(name, { selector: "div" });
}
/** A New Plugin menu entry; entries with a description add it to the name. */
function addMenuItem(title: string) {
  return screen.getByRole("menuitem", { name: new RegExp(`^${title}( |$)`) });
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
  await findCard("Manage Workspace MCP");
  expect(card("View Reports API")).toBeVisible();
  expect(screen.getByRole("tab", { name: "Craft Apps" })).toBeDisabled();
  expect(queryCard("Manage Workspace service")).not.toBeInTheDocument();
  await setupUser().click(screen.getByRole("button", { name: copy.add.label }));
  expect(
    screen.queryByRole("menuitem", { name: /^Craft Apps/ })
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
  await findCard("Manage Renamed workspace");
  await setupUser().click(screen.getByRole("button", { name: copy.add.label }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await setupUser().click(addMenuItem(copy.kind.mcp));
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
  await screen.findByText(copy.state.noResults.title);
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(await findCard("Manage Workspace MCP")).toBeVisible();
  expect(
    screen.queryByRole("dialog", { name: "MCP setup" })
  ).not.toBeInTheDocument();
  expect(mcpReads).toBe(2);
});

test("lists native records with colliding IDs as cards that open their modals", async () => {
  const network = mockNetwork();
  render(<PluginsPage />);
  const mcpCard = await findCard("Manage Workspace MCP");
  const openapiCard = await findCard("View Reports API");
  expect(network.mock.calls.map(([url]) => String(url)).sort()).toEqual([
    "/api/admin/mcp/servers",
    "/api/enterprise-settings",
    "/api/settings",
    "/api/tool/openapi",
  ]);
  expect(within(mcpCard).getByText("MCP")).toBeVisible();
  expect(within(mcpCard).getByText("Connected")).toBeVisible();
  expect(within(openapiCard).getByText("OpenAPI")).toBeVisible();
  expect(within(openapiCard).getByText("Connected")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /^Chat (on|off)$/ })
  ).not.toBeInTheDocument();
  const user = setupUser();
  await user.click(mcpCard);
  expect(screen.getByRole("dialog", { name: "MCP plugin 7" })).toBeVisible();
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await user.click(openapiCard);
  expect(
    screen.getByRole("dialog", { name: "OpenAPI plugin 7" })
  ).toBeVisible();
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  expect(mockPush).not.toHaveBeenCalled();
  expect(mockReplace).not.toHaveBeenCalled();
});

test("closing an opened plugin's modal returns to the list without routing", async () => {
  mockNetwork();
  render(<PluginsPage />);
  const user = setupUser();
  await user.click(await findCard("Manage Workspace MCP"));
  expect(screen.getByRole("status", { name: "Opened with" })).toHaveTextContent(
    ""
  );
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(card("Manage Workspace MCP")).toBeVisible();
  expect(card("View Reports API")).toBeVisible();
  expect(mockPush).not.toHaveBeenCalled();
  expect(mockReplace).not.toHaveBeenCalled();
});

test("the OpenAPI gear opens the plugin's modal without routing", async () => {
  mockNetwork();
  render(<PluginsPage />);
  const openapiCard = await findCard("View Reports API");
  await setupUser().click(
    within(openapiCard).getByRole("button", { name: "Manage Reports API" })
  );
  expect(
    screen.getByRole("dialog", { name: "OpenAPI plugin 7" })
  ).toBeVisible();
  expect(mockPush).not.toHaveBeenCalled();
});

test("a plugin parameter opens that plugin once and clears the URL", async () => {
  mockNetwork();
  mockSearchParams = new URLSearchParams(
    "plugin=mcp:7&trigger_fetch=true&enable_chat=true"
  );
  const view = render(<PluginsPage />);
  expect(
    await screen.findByRole("dialog", { name: "MCP plugin 7" })
  ).toBeVisible();
  expect(screen.getByRole("status", { name: "Opened with" })).toHaveTextContent(
    "trigger_fetch=true&enable_chat=true"
  );
  expect(mockReplace).toHaveBeenCalledTimes(1);
  expect(mockReplace).toHaveBeenCalledWith("/admin/plugins", {
    scroll: false,
  });
  view.rerender(<PluginsPage />);
  await setupUser().click(screen.getByRole("button", { name: "Close" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  // The router has not cleared the URL yet; the page must not reopen.
  view.rerender(<PluginsPage />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(mockReplace).toHaveBeenCalledTimes(1);
  mockSearchParams = new URLSearchParams();
  view.rerender(<PluginsPage />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(mockPush).not.toHaveBeenCalled();
});

test("waits for the lists before it opens a plugin from the URL", async () => {
  const openapi = deferred<Response>();
  const network = mockNetwork();
  const respond = network.getMockImplementation();
  if (!respond) throw new Error("Expected the network mock");
  network.mockImplementation(async (input, init) =>
    String(input) === "/api/tool/openapi"
      ? openapi.promise
      : respond(input, init)
  );
  mockSearchParams = new URLSearchParams("plugin=openapi:7");
  render(<PluginsPage />);
  await findCard("Manage Workspace MCP");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(mockReplace).not.toHaveBeenCalled();
  openapi.resolve(new Response(JSON.stringify([tool])));
  expect(
    await screen.findByRole("dialog", { name: "OpenAPI plugin 7" })
  ).toBeVisible();
  expect(mockReplace).toHaveBeenCalledWith("/admin/plugins", {
    scroll: false,
  });
});

test.each(["mcp:99", "openapi:99", "external-app:7", "mcp:abc", "nope"])(
  "a plugin parameter %s that is not in the list opens nothing and clears the URL",
  async (value) => {
    mockNetwork();
    mockSearchParams = new URLSearchParams({ plugin: value, tab: "tools" });
    render(<PluginsPage />);
    await findCard("Manage Workspace MCP");
    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith("/admin/plugins", {
        scroll: false,
      })
    );
    expect(mockReplace).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  }
);

test.each([
  MCPConnectionStatus.NOT_CONNECTED,
  MCPConnectionStatus.REAUTH_REQUIRED,
])("an MCP server with connection status %s needs sign-in", async (status) => {
  mockNetwork({
    servers: [
      {
        ...mockServer,
        status: MCPServerStatus.AWAITING_AUTH,
        connection_status: status,
      },
    ],
  });
  render(<PluginsPage />);
  const mcpCard = await findCard("Manage Workspace MCP");
  expect(within(mcpCard).getByText("Needs sign-in")).toBeVisible();
  expect(within(mcpCard).queryByText("Connected")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("tab", { name: "Needs sign-in" })
  ).not.toBeInTheDocument();
});

test("includes external apps with colliding IDs only for full admins", async () => {
  mockFullAdmin = true;
  mockNetwork();
  render(<PluginsPage />);
  const appCard = await findCard("Manage Workspace service");
  expect(within(appCard).getByText("Craft")).toBeVisible();
  expect(card("Manage Workspace MCP")).toBeVisible();
  expect(card("View Reports API")).toBeVisible();
  await setupUser().click(appCard);
  expect(screen.getByRole("dialog", { name: "App plugin 7" })).toBeVisible();
  expect(mockPush).not.toHaveBeenCalled();
  await setupUser().click(screen.getByRole("button", { name: "Close" }));
  const filters = screen.getByRole("tablist", { name: "Plugin type" });
  const user = setupUser();
  await user.click(within(filters).getByRole("tab", { name: "MCP" }));
  expect(card("Manage Workspace MCP")).toBeVisible();
  expect(queryCard("View Reports API")).not.toBeInTheDocument();
  await user.click(within(filters).getByRole("tab", { name: "OpenAPI" }));
  expect(card("View Reports API")).toBeVisible();
  expect(queryCard("Manage Workspace MCP")).not.toBeInTheDocument();
  await user.click(within(filters).getByRole("tab", { name: "Craft Apps" }));
  expect(card("Manage Workspace service")).toBeVisible();
  expect(queryCard("View Reports API")).not.toBeInTheDocument();
  await user.click(within(filters).getByRole("tab", { name: "All" }));
  expect(card("View Reports API")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Add Sentry" })
  ).not.toBeInTheDocument();
});

test("never requests external admin records or provider options for scoped action managers", async () => {
  mockCanCreate = false;
  mockScopedManager = true;
  const network = mockNetwork();
  render(<PluginsPage />);
  await findCard("Manage Workspace MCP");
  expect(screen.getByRole("tab", { name: "Craft Apps" })).toBeDisabled();
  await setupUser().click(screen.getByRole("button", { name: copy.add.label }));
  expect(
    screen.queryByRole("menuitem", { name: /^Craft Apps/ })
  ).not.toBeInTheDocument();
  await setupUser().click(addMenuItem(copy.kind.mcp));
  expect(screen.getByRole("button", { name: "Add Sentry" })).toBeVisible();
  expect(
    network.mock.calls.some(([url]) =>
      String(url).startsWith("/api/build/admin/apps")
    )
  ).toBe(false);
});

test("the card's settings button opens the availability menu without opening the plugin", async () => {
  mockFullAdmin = true;
  mockNetwork({
    servers: [
      { ...mockServer, default_chat_enabled: true, available_in_craft: true },
    ],
  });
  render(<PluginsPage />);
  const user = setupUser();
  const mcpCard = await findCard("Manage Workspace MCP");
  await user.click(
    within(mcpCard).getByRole("button", {
      name: /^(Enable|Disable) for workspace$|^Manage workspace availability$/,
    })
  );
  expect(
    await screen.findByRole("menuitem", { name: /Disable for main Chat/ })
  ).toBeVisible();
  expect(
    screen.getByRole("menuitem", { name: /Disable for Craft/ })
  ).toBeVisible();
  expect(screen.getAllByRole("menu")).toHaveLength(1);
  await user.click(screen.getByRole("menuitem", { name: /Disable for Craft/ }));
  expect(mockPush).not.toHaveBeenCalled();
});

test("filters by description and URL and clears a search without losing either resource", async () => {
  mockNetwork();
  render(<PluginsPage />);
  await findCard("Manage Workspace MCP");
  const user = setupUser();
  const search = screen.getByRole("textbox", { name: copy.search.placeholder });
  await user.type(search, "weekly");
  expect(card("View Reports API")).toBeVisible();
  expect(queryCard("Manage Workspace MCP")).not.toBeInTheDocument();
  await user.clear(search);
  await user.type(search, "workspace.example.com");
  expect(card("Manage Workspace MCP")).toBeVisible();
  await user.clear(search);
  await user.type(search, "missing");
  expect(screen.getByText(messages.common.searchNoResults.title)).toBeVisible();
  expect(
    screen.queryByText(copy.state.noResults.title)
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "View all plugins" })
  ).not.toBeInTheDocument();
  const field = search.closest("[role='presentation']");
  if (!(field instanceof HTMLElement)) throw new Error("Missing search field");
  await user.click(within(field).getByRole("button"));
  expect(search).toHaveValue("");
  expect(card("View Reports API")).toBeVisible();
  expect(card("Manage Workspace MCP")).toBeVisible();
});

test.each([
  {
    mcpStatus: 503,
    openapiStatus: 200,
    error: copy.state.mcpError,
    successfulCard: "View Reports API",
    retryUrl: "/api/admin/mcp/servers",
  },
  {
    mcpStatus: 200,
    openapiStatus: 503,
    error: copy.state.openapiError,
    successfulCard: "Manage Workspace MCP",
    retryUrl: "/api/tool/openapi",
  },
])(
  "keeps the successful list visible when $retryUrl fails and retries only that list",
  async ({ mcpStatus, openapiStatus, error, successfulCard, retryUrl }) => {
    const network = mockNetwork({ mcpStatus, openapiStatus });
    render(<PluginsPage />);
    expect(await findCard(successfulCard)).toBeVisible();
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
    expect(
      screen.queryByText(copy.state.noResults.title)
    ).not.toBeInTheDocument();
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
  expect(await findCard("View Reports API")).toBeVisible();
  expect(
    screen.getByRole("status", { name: copy.state.loading })
  ).toBeVisible();
  pending.resolve(new Response(JSON.stringify({ mcp_servers: [mockServer] })));
  expect(await findCard("Manage Workspace MCP")).toBeVisible();
});

test("an empty installation shows one empty state and adds plugins from New Plugin", async () => {
  mockNetwork({ empty: true });
  render(<PluginsPage />);
  expect(await screen.findByText(copy.state.noResults.title)).toBeVisible();
  expect(screen.getByText(copy.state.noResults.description)).toBeVisible();
  expect(
    screen.queryByText(messages.common.searchNoResults.title)
  ).not.toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: copy.add.label })).toHaveLength(
    1
  );
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: copy.add.label }));
  expect(addMenuItem(copy.kind.mcp)).toHaveTextContent(copy.add.mcpDescription);
  await user.click(addMenuItem(copy.kind.mcp));
  expect(screen.getByRole("button", { name: "Add Linear" })).toBeVisible();
  expect(screen.getByText(copy.catalog.atlassian.summary)).toBeVisible();
});

test("an empty filter shows the same empty state as an empty installation", async () => {
  mockNetwork({ servers: [] });
  render(<PluginsPage />);
  await findCard("View Reports API");
  await setupUser().click(screen.getByRole("tab", { name: "MCP" }));
  expect(screen.getByText(copy.state.noResults.title)).toBeVisible();
  expect(screen.getByText(copy.state.noResults.description)).toBeVisible();
});

test("full admins can open an app-only catalog from New Plugin", async () => {
  mockFullAdmin = true;
  const network = mockNetwork();
  render(<PluginsPage />);
  await findCard("Manage Workspace service");
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: copy.add.label }));
  expect(screen.getAllByRole("menuitem")).toHaveLength(3);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(
    network.mock.calls.some(([url]) => String(url).endsWith("built-in/options"))
  ).toBe(false);
  await user.click(addMenuItem(copy.kind["external-app"]));
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
    await setupUser().click(addMenuItem(copy.kind.mcp));
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

test("completing custom MCP setup closes the modal and refreshes without opening the server", async () => {
  const network = mockNetwork();
  render(<PluginsPage />);
  await findCard("Manage Workspace MCP");
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: copy.add.label }));
  await user.click(addMenuItem(copy.kind.mcp));
  await user.click(screen.getByRole("button", { name: copy.add.mcp }));
  expect(screen.getByRole("textbox", { name: "Server URL" })).toHaveValue("");
  const reads = () =>
    network.mock.calls.filter(([url]) => url === "/api/admin/mcp/servers")
      .length;
  const before = reads();
  await user.click(screen.getByRole("button", { name: "Complete setup" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await waitFor(() => expect(reads()).toBe(before + 1));
  expect(mockPush).not.toHaveBeenCalled();
});

test("adding an OpenAPI action closes the modal and refreshes without opening it", async () => {
  const network = mockNetwork();
  render(<PluginsPage />);
  await findCard("View Reports API");
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: copy.add.label }));
  expect(addMenuItem(copy.kind.openapi)).toHaveTextContent(
    messages.actions.addOpenApiModal.addHeader.description
  );
  await user.click(addMenuItem(copy.kind.openapi));
  expect(screen.getByRole("dialog", { name: "OpenAPI setup" })).toBeVisible();
  const reads = () =>
    network.mock.calls.filter(([url]) => url === "/api/tool/openapi").length;
  const before = reads();
  await user.click(screen.getByRole("button", { name: "Create action" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await waitFor(() => expect(reads()).toBe(before + 1));
  expect(mockPush).not.toHaveBeenCalled();
});

test("a creation deep link replaces an open catalog instead of opening a second dialog", async () => {
  mockNetwork();
  const view = render(<PluginsPage />);
  await findCard("Manage Workspace MCP");
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: copy.add.label }));
  await user.click(addMenuItem(copy.kind.mcp));
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
