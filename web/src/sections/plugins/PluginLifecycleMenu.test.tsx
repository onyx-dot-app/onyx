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

let mockFullAdmin = true;
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
  users_can_manage_policies: true,
};
beforeEach(() => {
  mockFullAdmin = true;
  writes = [];
  reads = [];
  failDelete = false;
  jest.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (init?.method && init.method !== "GET") {
      const body: unknown = init.body ? JSON.parse(String(init.body)) : null;
      writes.push({ path, body, method: init.method });
      if (failDelete && init.method === "DELETE")
        return new Response(JSON.stringify({ detail: "Deletion failed" }), {
          status: 400,
        });
      return new Response(JSON.stringify({}));
    }
    reads.push(path);
    throw new Error(`Unexpected request ${path}`);
  });
});
afterEach(() => jest.restoreAllMocks());

test("MCP directory omits availability controls", () => {
  render(<PluginLifecycleMenu plugin={{ kind: "mcp", server }} />);
  expect(
    screen.queryByRole("button", {
      name: /workspace availability|for workspace/,
    })
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  expect(reads).toEqual([]);
});

test("OpenAPI directory omits availability controls", () => {
  render(<PluginLifecycleMenu plugin={{ kind: "openapi", tool }} />);
  expect(
    screen.queryByRole("button", {
      name: /for workspace|workspace availability/,
    })
  ).not.toBeInTheDocument();
  expect(reads).toEqual([]);
});

test.each([false, true])(
  "external app directory has no availability menu (managed=%s)",
  (managed) => {
    render(
      <PluginLifecycleMenu
        plugin={{
          kind: "external-app",
          app: { ...app, is_onyx_managed: managed },
        }}
      />
    );
    expect(
      screen.queryByRole("button", {
        name: /for workspace|workspace availability/,
      })
    ).not.toBeInTheDocument();
    if (managed)
      expect(
        screen.queryByRole("button", { name: "Delete" })
      ).not.toBeInTheDocument();
    expect(reads).toEqual([]);
  }
);

test("non-full admins cannot open external app lifecycle controls", () => {
  mockFullAdmin = false;
  render(<PluginLifecycleMenu plugin={{ kind: "external-app", app }} />);
  expect(
    screen.queryByRole("button", {
      name: "Delete",
    })
  ).not.toBeInTheDocument();
  expect(reads).toEqual([]);
});

test("deletes an external app only after confirmation", async () => {
  render(
    <PluginLifecycleMenu
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
  render(<PluginLifecycleMenu plugin={{ kind: "openapi", tool }} />);
  await user.click(await screen.findByRole("button", { name: "Delete" }));
  expect(writes).toHaveLength(0);
  const dialog = await screen.findByRole("dialog");
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
  render(<PluginLifecycleMenu plugin={{ kind: "mcp", server }} />);
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

test("hides controls when the resource grants no lifecycle permission", () => {
  mockFullAdmin = false;
  render(
    <PluginLifecycleMenu
      plugin={{ kind: "openapi", tool: { ...tool, permissions: {} } }}
    />
  );
  expect(
    screen.queryByRole("button", {
      name: "Delete",
    })
  ).not.toBeInTheDocument();
  expect(reads).toEqual([]);
});
