import { MCPConnectionStatus } from "@/lib/mcp/types";
import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import PluginLifecycleMenu from "@/sections/plugins/PluginLifecycleMenu";
import { MCPServerStatus, type MCPServer } from "@/lib/mcp/types";
import type { ToolSnapshot } from "@/lib/tools/types";
import type { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";
import { consumeMcpChatEnableIntent } from "@/sections/actions/mcpChatEnableIntent";

jest.mock("@/providers/UserProvider", () => {
  const actual = jest.requireActual<typeof import("@/providers/UserProvider")>(
    "@/providers/UserProvider"
  );
  return {
    ...actual,
    useUser: () => ({ ...actual.useUser(), user: { id: "admin-user" } }),
  };
});

let mockFullAdmin = true;
const mockPush = jest.fn();
const onOpen = jest.fn<void, [URLSearchParams?]>();
jest.mock("next/navigation", () => ({
  usePathname: () => "/admin/plugins",
  useRouter: () => ({ push: mockPush }),
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({ isGlobalHolder: mockFullAdmin }),
}));

const server: MCPServer = {
  connection_status: null,
  id: 7,
  name: "Workspace",
  server_url: "https://example.com/mcp",
  owner: "admin",
  status: MCPServerStatus.CONNECTED,
  is_public: true,
  groups: [],
  users: [],
  tool_count: 2,
  available_in_craft: true,
  permissions: { edit: true, delete: true },
};
const tool: ToolSnapshot = {
  id: 42,
  name: "Reports",
  display_name: "Reports",
  description: "Read reports",
  definition: {},
  custom_headers: [],
  passthrough_auth: false,
  oauth_config_id: null,
  in_code_tool_id: null,
  enabled: true,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: false,
  permissions: { toggle: true, delete: true },
};
let writes: { path: string; body: unknown; method: string }[];
let reads: string[];
let failDelete: boolean;
let failDisable: boolean;
let serverTools: ToolSnapshot[];
let defaultToolIds: number[];
const app: ExternalAppAdminResponse = {
  id: 7,
  name: "Workspace service",
  app_type: "CUSTOM",
  enabled: true,
  upstream_url_patterns: [],
  auth_template: {},
  organization_credentials: {},
  credential_placeholder_keys: [],
  actions: [],
  associated_skills: [],
  is_onyx_managed: false,
};
beforeEach(() => {
  mockFullAdmin = true;
  mockPush.mockClear();
  onOpen.mockClear();
  writes = [];
  reads = [];
  failDelete = false;
  failDisable = false;
  serverTools = [tool];
  defaultToolIds = [42, 99];
  jest.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (init?.method && init.method !== "GET") {
      const body: unknown = init.body ? JSON.parse(String(init.body)) : null;
      writes.push({ path, body, method: init.method });
      if (failDisable && init.method === "PATCH")
        return new Response(
          JSON.stringify({ detail: "Availability update failed" }),
          {
            status: 400,
          }
        );
      if (failDelete && init.method === "DELETE")
        return new Response(JSON.stringify({ detail: "Deletion failed" }), {
          status: 400,
        });
      return new Response(
        JSON.stringify(
          path === "/api/admin/default-assistant"
            ? { tool_ids: [99], is_default_persona: true }
            : {}
        )
      );
    }
    reads.push(path);
    if (path === "/api/admin/default-assistant/configuration")
      return new Response(
        JSON.stringify({ tool_ids: defaultToolIds, is_default_persona: true })
      );
    if (path === "/api/admin/mcp/server/7/tools/snapshots?source=db")
      return new Response(JSON.stringify(serverTools));
    if (path === "/api/settings")
      return new Response(JSON.stringify({ onyx_craft_available: true }));
    if (path === "/api/enterprise-settings")
      return new Response(JSON.stringify({ onyx_craft_available: true }));
    throw new Error(`Unexpected request ${path}`);
  });
});
afterEach(() => jest.restoreAllMocks());

test.each([
  {
    chat: true,
    craft: true,
    craftAvailable: true,
    label: "Disable for workspace",
  },
  {
    chat: false,
    craft: false,
    craftAvailable: true,
    label: "Enable for workspace",
  },
  {
    chat: true,
    craft: false,
    craftAvailable: true,
    label: "Manage workspace availability",
  },
  {
    chat: false,
    craft: true,
    craftAvailable: true,
    label: "Manage workspace availability",
  },
  {
    chat: undefined,
    craft: true,
    craftAvailable: true,
    label: "Manage workspace availability",
  },
  {
    chat: true,
    craft: undefined,
    craftAvailable: true,
    label: "Manage workspace availability",
  },
  {
    chat: null,
    craft: false,
    craftAvailable: true,
    label: "Manage workspace availability",
  },
  {
    chat: false,
    craft: undefined,
    craftAvailable: true,
    label: "Manage workspace availability",
  },
  {
    chat: true,
    craft: false,
    craftAvailable: false,
    label: "Disable for workspace",
  },
  {
    chat: false,
    craft: true,
    craftAvailable: false,
    label: "Enable for workspace",
  },
  {
    chat: undefined,
    craft: true,
    craftAvailable: false,
    label: "Manage workspace availability",
  },
])(
  "MCP availability label follows chat=$chat, craft=$craft, Craft available=$craftAvailable",
  async ({ chat, craft, craftAvailable, label }) => {
    render(
      <PluginLifecycleMenu
        craftAvailable={craftAvailable}
        plugin={{
          kind: "mcp",
          server: {
            ...server,
            default_chat_enabled: chat,
            available_in_craft: craft,
          },
        }}
      />
    );
    const trigger = screen.getByRole("button", { name: label });
    expect(reads).toEqual([]);
    await setupUser().click(trigger);
    expect(await screen.findByRole("button", { name: label })).toBeVisible();
    expect(writes).toEqual([]);
  }
);

test("the OpenAPI gear opens the plugin's modal instead of a menu", async () => {
  render(
    <PluginLifecycleMenu
      craftAvailable
      plugin={{ kind: "openapi", tool }}
      onOpen={onOpen}
    />
  );
  expect(
    screen.queryByRole("button", {
      name: /^(Enable|Disable) for workspace$|^Manage workspace availability$/,
    })
  ).not.toBeInTheDocument();
  await setupUser().click(
    screen.getByRole("button", { name: "Manage Reports" })
  );
  expect(onOpen).toHaveBeenCalledTimes(1);
  expect(onOpen.mock.calls[0]?.[0]).toBeUndefined();
  expect(mockPush).not.toHaveBeenCalled();
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(reads).toEqual([]);
  expect(writes).toEqual([]);
});

test.each([true, false])(
  "Craft app availability label uses its global enabled=%s state",
  async (enabled) => {
    render(
      <PluginLifecycleMenu
        plugin={{ kind: "external-app", app: { ...app, enabled } }}
      />
    );
    const label = enabled ? "Disable for workspace" : "Enable for workspace";
    await setupUser().click(screen.getByRole("button", { name: label }));
    expect(screen.getByRole("button", { name: label })).toBeVisible();
    expect(writes).toEqual([]);
  }
);

test("does not fetch configuration or tools until the menu opens", () => {
  render(
    <PluginLifecycleMenu craftAvailable plugin={{ kind: "mcp", server }} />
  );
  expect(
    screen.getByRole("button", {
      name: /^(Enable|Disable) for workspace$|^Manage workspace availability$/,
    })
  ).toBeInTheDocument();
  expect(reads).toEqual([]);
});

test("external availability writes only Craft enabled and never loads main Chat configuration", async () => {
  render(
    <PluginLifecycleMenu
      craftAvailable
      plugin={{ kind: "external-app", app }}
    />
  );
  const user = setupUser();
  await user.click(
    screen.getByRole("button", {
      name: /^(Enable|Disable) for workspace$|^Manage workspace availability$/,
    })
  );
  await user.click(screen.getByRole("menuitem", { name: "Disable for Craft" }));
  await waitFor(() =>
    expect(writes).toContainEqual({
      path: "/api/build/admin/apps/7",
      method: "PATCH",
      body: { enabled: false },
    })
  );
  expect(reads).toEqual([]);
});

test("managed external apps expose availability but cannot be deleted", async () => {
  render(
    <PluginLifecycleMenu
      craftAvailable
      plugin={{ kind: "external-app", app: { ...app, is_onyx_managed: true } }}
    />
  );
  await setupUser().click(
    screen.getByRole("button", {
      name: /^(Enable|Disable) for workspace$|^Manage workspace availability$/,
    })
  );
  expect(
    screen.queryByRole("button", { name: "Delete" })
  ).not.toBeInTheDocument();
});

test("non-full admins cannot open external app lifecycle controls", () => {
  mockFullAdmin = false;
  render(
    <PluginLifecycleMenu
      craftAvailable
      plugin={{ kind: "external-app", app }}
    />
  );
  expect(
    screen.queryByRole("button", {
      name: /^(Enable|Disable) for workspace$|^Manage workspace availability$/,
    })
  ).not.toBeInTheDocument();
  expect(reads).toEqual([]);
});

test("deletes an external app only after confirmation", async () => {
  render(
    <PluginLifecycleMenu
      craftAvailable
      plugin={{
        kind: "external-app",
        app: {
          ...app,
          associated_skills: [
            { id: "skill-read", name: "lookup", is_valid: true },
            { id: "skill-write", name: "update", is_valid: true },
          ],
        },
      }}
    />
  );
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Delete" }));
  expect(writes).toEqual([]);
  expect(
    screen.getByText(
      "2 associated custom skills will be kept, unlinked from this app, and disabled for everyone."
    )
  ).toBeInTheDocument();
  await user.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Delete app",
    })
  );
  await waitFor(() =>
    expect(writes).toContainEqual({
      path: "/api/build/admin/apps/7",
      method: "DELETE",
      body: null,
    })
  );
});

test("confirms deletion from the directory and reports failures inline", async () => {
  failDelete = true;
  const user = setupUser();
  render(
    <PluginLifecycleMenu craftAvailable plugin={{ kind: "openapi", tool }} />
  );
  await user.click(await screen.findByRole("button", { name: "Delete" }));
  expect(writes).toHaveLength(0);
  const dialog = await screen.findByRole("dialog", { name: "Delete Reports" });
  await user.click(within(dialog).getByRole("button", { name: "Delete" }));
  expect(
    await within(dialog).findByText(/Deletion failed/)
  ).toBeInTheDocument();
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  failDelete = false;
  await user.click(within(dialog).getByRole("button", { name: "Delete" }));
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  );
  expect(writes.filter((write) => write.method === "DELETE")).toHaveLength(2);
});

test("MCP deletion warns that the server and tools are deleted for the organization", async () => {
  const user = setupUser();
  render(
    <PluginLifecycleMenu craftAvailable plugin={{ kind: "mcp", server }} />
  );
  await user.click(screen.getByRole("button", { name: "Delete" }));
  const dialog = await screen.findByRole("dialog");
  expect(
    within(dialog).getByText(
      "This deletes Workspace and all its tools for everyone in your organization. Deletion is irreversible."
    )
  ).toBeVisible();
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(writes).toEqual([]);
  await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(writes).toEqual([]);
});

test("removes only this server's tool IDs from main Chat", async () => {
  const user = setupUser();
  render(
    <PluginLifecycleMenu craftAvailable plugin={{ kind: "mcp", server }} />
  );
  await user.click(
    screen.getByRole("button", {
      name: /^(Enable|Disable) for workspace$|^Manage workspace availability$/,
    })
  );
  const action = await screen.findByRole("menuitem", {
    name: /Disable.*main Chat/,
  });
  expect(
    screen.getByRole("menuitem", { name: /Disable for Craft/ })
  ).toBeVisible();
  await user.click(action);
  expect(writes).toEqual([]);
  const dialog = await screen.findByRole("dialog");
  expect(
    within(dialog).getByText(/everyone in your organization/)
  ).toBeVisible();
  expect(
    within(dialog).getByText(/Custom agents are not affected/)
  ).toBeVisible();
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  await user.click(
    within(dialog).getByRole("button", { name: "Disable for main Chat" })
  );
  await waitFor(() =>
    expect(writes).toContainEqual({
      path: "/api/admin/default-assistant",
      method: "PATCH",
      body: { tool_ids: [99] },
    })
  );
});

test("scoped editors can change Craft but not main Chat", async () => {
  mockFullAdmin = false;
  const user = setupUser();
  render(
    <PluginLifecycleMenu craftAvailable plugin={{ kind: "mcp", server }} />
  );
  await user.click(
    screen.getByRole("button", {
      name: /^(Enable|Disable) for workspace$|^Manage workspace availability$/,
    })
  );
  expect(
    screen.queryByRole("menuitem", { name: /main Chat/ })
  ).not.toBeInTheDocument();
  await user.click(
    await screen.findByRole("menuitem", { name: /Disable.*Craft/ })
  );
  expect(writes).toEqual([]);
  await user.click(
    within(await screen.findByRole("dialog")).getByRole("button", {
      name: "Disable for Craft",
    })
  );
  await waitFor(() =>
    expect(writes).toContainEqual({
      path: "/api/admin/mcp/server/7",
      method: "PATCH",
      body: { available_in_craft: false },
    })
  );
  expect(reads).not.toContain(
    "/api/admin/mcp/server/7/tools/snapshots?source=db"
  );
});

test.each(["main Chat", "Craft"])(
  "cancelling organization-wide %s disable makes no changes",
  async (surface) => {
    const user = setupUser();
    render(
      <PluginLifecycleMenu craftAvailable plugin={{ kind: "mcp", server }} />
    );
    await user.click(
      screen.getByRole("button", {
        name: /^(Enable|Disable) for workspace$|^Manage workspace availability$/,
      })
    );
    const action = await screen.findByRole("menuitem", {
      name: new RegExp(`Disable for ${surface}`),
    });
    expect(
      within(action).getByText("All users in your organization")
    ).toBeVisible();
    await user.click(action);
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(/everyone in your organization/)
    ).toBeVisible();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(writes).toEqual([]);
  }
);

test("failed Craft disable stays open for retry", async () => {
  failDisable = true;
  const user = setupUser();
  render(
    <PluginLifecycleMenu craftAvailable plugin={{ kind: "mcp", server }} />
  );
  await user.click(
    screen.getByRole("button", {
      name: /^(Enable|Disable) for workspace$|^Manage workspace availability$/,
    })
  );
  await user.click(
    await screen.findByRole("menuitem", { name: /Disable for Craft/ })
  );
  const dialog = await screen.findByRole("dialog");
  await user.click(
    within(dialog).getByRole("button", { name: "Disable for Craft" })
  );
  expect(
    await within(dialog).findByText(/Availability update failed/)
  ).toBeVisible();
  failDisable = false;
  await user.click(
    within(dialog).getByRole("button", { name: "Disable for Craft" })
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  );
  expect(writes).toHaveLength(2);
  expect(
    writes.every(
      (write) =>
        JSON.stringify(write.body) ===
        JSON.stringify({ available_in_craft: false })
    )
  ).toBe(true);
});

test("enabling Craft stays immediate", async () => {
  const user = setupUser();
  render(
    <PluginLifecycleMenu
      craftAvailable
      plugin={{ kind: "mcp", server: { ...server, available_in_craft: false } }}
    />
  );
  await user.click(
    screen.getByRole("button", {
      name: /^(Enable|Disable) for workspace$|^Manage workspace availability$/,
    })
  );
  await user.click(
    await screen.findByRole("menuitem", { name: "Enable for Craft" })
  );
  await waitFor(() =>
    expect(writes).toContainEqual({
      path: "/api/admin/mcp/server/7",
      method: "PATCH",
      body: { available_in_craft: true },
    })
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("opens authentication instead of disabling Enable for a server awaiting sign-in", async () => {
  serverTools = [];
  const user = setupUser();
  render(
    <PluginLifecycleMenu
      craftAvailable
      plugin={{
        kind: "mcp",
        server: {
          ...server,
          status: MCPServerStatus.AWAITING_AUTH,
          default_chat_enabled: false,
          connection_status: MCPConnectionStatus.NOT_CONNECTED,
          permissions: { ...server.permissions, authenticate: true },
        },
      }}
      onOpen={onOpen}
    />
  );
  await user.click(
    screen.getByRole("button", {
      name: /^(Enable|Disable) for workspace$|^Manage workspace availability$/,
    })
  );
  const enable = await screen.findByRole("menuitem", {
    name: "Enable for main Chat",
  });
  expect(enable).not.toHaveAttribute("aria-disabled", "true");
  await user.click(enable);
  expect(mockPush).not.toHaveBeenCalled();
  expect(onOpen).toHaveBeenCalledTimes(1);
  const params = onOpen.mock.calls[0]?.[0];
  if (!params) throw new Error("Expected the modal to open with parameters");
  expect(params.get("tab")).toBe("authentication");
  expect(params.get("enable_chat")).toBe("true");
  expect(
    consumeMcpChatEnableIntent(params.get("enable_chat_intent"), {
      userId: "admin-user",
      serverId: 7,
    })
  ).toBe(true);
  expect(writes).toEqual([]);
});

test("hides controls when the resource grants no lifecycle permission", () => {
  mockFullAdmin = false;
  render(
    <PluginLifecycleMenu
      craftAvailable
      plugin={{ kind: "openapi", tool: { ...tool, permissions: {} } }}
    />
  );
  expect(
    screen.queryByRole("button", {
      name: /^(Enable|Disable) for workspace$|^Manage workspace availability$/,
    })
  ).not.toBeInTheDocument();
  expect(reads).toEqual([]);
});
