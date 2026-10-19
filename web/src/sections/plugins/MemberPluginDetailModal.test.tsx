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
import type { SkillsList } from "@/lib/skills/types";
import type { MemberPlugin } from "@/lib/plugins/member";
import { NextIntlClientProvider } from "next-intl";
import {
  builtinFixture,
  customFixture,
} from "@/lib/skills/__fixtures__/picker";
import {
  jsonResponse,
  memberServer,
  memberTool,
  storedMcpTool,
  memberApp,
  memberPluginMessages,
} from "@/sections/plugins/__tests__/memberPluginFixtures";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
  usePathname: () => "/app/plugins",
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

test("disabled Craft hides app-only metadata, skills recovery, and launch action", () => {
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
  expect(requests).not.toHaveBeenCalledWith("/api/skills");
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

function mockSkillsRequests(skills: SkillsList) {
  return jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) =>
      jsonResponse(
        String(input).includes("/action-policies/")
          ? { ...approvalApp, actions: [] }
          : skills
      )
    );
}

function show(
  plugin: MemberPlugin,
  onDisconnected = jest.fn(),
  surface?: "all" | "craft",
  options: { initialTab?: "approvals"; onClose?: () => void } = {}
) {
  return render(
    <NextIntlClientProvider locale="en" messages={memberPluginMessages}>
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
  expect(screen.getByText("Connected")).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("Connected");
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
    const requests = mockSkillsRequests({ builtins: [], customs: [] });
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
    expect(screen.getByRole("status")).toHaveTextContent("Connected");
    expect(
      requests.mock.calls.every(([input]) => !String(input).includes("/admin"))
    ).toBe(true);
  }
);

test.each([undefined, []])(
  "Craft app details omit missing service URLs (%s)",
  (service_urls) => {
    const requests = mockSkillsRequests({ builtins: [], customs: [] });
    show({
      kind: "external-app",
      app: memberApp({ name: "Linear", app_type: "LINEAR", service_urls }),
      connection: { kind: "connected", ownership: "user" },
    });
    expect(screen.queryByText(/https?:\/\//)).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Connected");
    expect(
      requests.mock.calls.every(([input]) => !String(input).includes("/admin"))
    ).toBe(true);
  }
);

test("Craft App details share the connection card and searchable Skills tab without admin data", async () => {
  const skill = builtinFixture({
    name: "GitHub workflow",
    external_app: {
      external_app_id: 7,
      name: "GitHub",
      enabled: true,
      ready: true,
    },
  });
  const requests = mockSkillsRequests({ builtins: [skill], customs: [] });
  show({
    kind: "external-app",
    app: memberApp({ authenticated: true }),
    connection: { kind: "connected", ownership: "user" },
  });
  expect(screen.getByRole("status")).toHaveTextContent("Connected");
  expect(screen.queryByRole("term")).not.toBeInTheDocument();
  expect(
    screen.queryByText("Use your account in Craft.")
  ).not.toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Tools" })).toBeVisible();
  await setupUser().click(screen.getByRole("tab", { name: "Skills" }));
  expect(await screen.findByText("GitHub workflow")).toBeVisible();
  expect(screen.getByRole("textbox", { name: "Search skills" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Review skills" })).toHaveAttribute(
    "href",
    "/craft/v1/skills?externalAppId=7"
  );
  expect(
    screen.queryByRole("button", { name: "Disconnect" })
  ).not.toBeInTheDocument();
  expect(
    requests.mock.calls.every(
      ([url]) =>
        String(url) === "/api/skills" ||
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
    .mockImplementation(async (input) =>
      jsonResponse(
        String(input) === "/api/skills" ? { builtins: [], customs: [] } : {}
      )
    );
  show(
    {
      kind: "external-app",
      app: memberApp({ authenticated: true }),
      connection: { kind: "connected", ownership: "user" },
    },
    disconnected
  );
  const user = setupUser();
  await waitFor(() => expect(requests).toHaveBeenCalledWith("/api/skills"));
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

test.each(["builtin", "custom"] as const)(
  "connected apps recover disabled associated %s skills",
  async (source) => {
    const skill = (source === "builtin" ? builtinFixture : customFixture)({
      enabled: false,
      external_app: {
        external_app_id: 7,
        name: "Workspace GitHub",
        enabled: true,
        ready: true,
      },
    });
    mockSkillsRequests({
      builtins: source === "builtin" ? [skill] : [],
      customs: source === "custom" ? [skill] : [],
    });
    show({
      kind: "external-app",
      app: memberApp({ authenticated: true }),
      connection: { kind: "connected", ownership: "user" },
    });
    expect(
      await screen.findByText(
        "Not all associated skills are enabled. This app may not work correctly."
      )
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Review skills" })).toBeVisible();
  }
);

test("enabled or unrelated skills do not mark a connected app as needing skill setup", async () => {
  mockSkillsRequests({
    builtins: [
      builtinFixture({
        enabled: true,
        external_app: {
          external_app_id: 7,
          name: "Workspace GitHub",
          enabled: true,
          ready: true,
        },
      }),
    ],
    customs: [
      customFixture({
        enabled: false,
        external_app: {
          external_app_id: 99,
          name: "Other app",
          enabled: true,
          ready: true,
        },
      }),
    ],
  });
  show({
    kind: "external-app",
    app: memberApp({ authenticated: true }),
    connection: { kind: "connected", ownership: "user" },
  });
  await waitFor(() => expect(global.fetch).toHaveBeenCalledWith("/api/skills"));
  expect(
    screen.queryByRole("button", { name: "Review skills" })
  ).not.toBeInTheDocument();
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
  expect(screen.getByRole("textbox", { name: "Search tools" })).toBeVisible();
  expect(requests).toHaveBeenCalledTimes(1);
  expect(requests).toHaveBeenCalledWith(
    "/api/build/action-policies/mcp_server/7"
  );
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
  expect(requests).toHaveBeenCalledWith(
    "/api/build/action-policies/mcp_server/7"
  );
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
  expect(screen.getByRole("status")).toHaveTextContent("Connected");
  expect(screen.getByRole("tab", { name: "Connection" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  expect(screen.queryByText("getUser")).not.toBeInTheDocument();
  await setupUser().click(screen.getByRole("tab", { name: "Tools" }));
  expect(screen.getByText("getUser")).toBeVisible();
  expect(screen.getByText("GET")).toBeVisible();
  expect(screen.getByText("/user")).toBeVisible();
  expect(screen.getByText("createRepo")).toBeVisible();
  expect(screen.getByText("POST")).toBeVisible();
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

test("OpenAPI endpoint search matches method, path, and summary and reports no results", async () => {
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
  const search = screen.getByRole("textbox", { name: "Search tools" });
  for (const query of ["post", "/deployments", "Schedule"]) {
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
  enabled: null,
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

test("approval loading retains the available tools until the editor is ready", async () => {
  const pending = deferred<Response>();
  const requests = jest.spyOn(global, "fetch").mockReturnValue(pending.promise);
  show({ ...approvalPlugin, tools: [storedMcpTool] });
  expect(requests).toHaveBeenCalledWith(
    "/api/build/action-policies/mcp_server/7"
  );
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
    screen.getByRole("textbox", {
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
      { name: "Disabled" }
    )
  );
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(close).toHaveBeenCalled());
  expect(requests).toHaveBeenCalledWith(
    "/api/build/action-policies/42",
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
      "/api/build/action-policies/42",
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

test("skill enable changes stay drafts across tabs and save only on Save", async () => {
  const skill = customFixture({
    enabled: false,
    external_app: {
      external_app_id: 7,
      name: "GitHub",
      enabled: true,
      ready: true,
    },
  });
  const requests = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (_input, init) =>
      jsonResponse(
        init?.method === "PUT"
          ? { ...skill, enabled: true }
          : { builtins: [], customs: [skill] }
      )
    );
  const onClose = jest.fn();
  show(
    {
      kind: "external-app",
      app: memberApp({ authenticated: true }),
      connection: { kind: "connected", ownership: "user" },
    },
    jest.fn(),
    "craft",
    { onClose }
  );
  const user = setupUser();
  expect(screen.getByRole("status")).toHaveTextContent(
    "You can start using this plugin."
  );
  expect(await screen.findByText("Issues")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Review skills" }));
  await user.click(
    await screen.findByRole("switch", { name: /Enable report-writer/ })
  );
  expect(requests.mock.calls.every(([, init]) => !init?.method)).toBe(true);
  await user.click(screen.getByRole("tab", { name: "Connection" }));
  await user.click(screen.getByRole("tab", { name: "Skills" }));
  expect(await screen.findByRole("switch")).toBeChecked();
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  expect(requests).toHaveBeenCalledWith(
    `/api/skills/${skill.id}/enabled`,
    expect.objectContaining({
      method: "PUT",
      body: JSON.stringify({ enabled: true, replace_conflict: false }),
    })
  );
});

test("reverting a skill draft leaves Save disabled without writing", async () => {
  const skill = customFixture({
    external_app: {
      external_app_id: 7,
      name: "GitHub",
      enabled: true,
      ready: true,
    },
  });
  const requests = mockSkillsRequests({ builtins: [], customs: [skill] });
  show({
    kind: "external-app",
    app: memberApp({ authenticated: true }),
    connection: { kind: "connected", ownership: "user" },
  });
  const user = setupUser();
  await user.click(screen.getByRole("tab", { name: "Skills" }));
  const toggle = await screen.findByRole("switch");
  await user.click(toggle);
  expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  await user.click(toggle);
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  expect(requests.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});

test("skill preview replaces the same modal content and Back preserves drafts", async () => {
  const skill = customFixture({
    external_app: {
      external_app_id: 7,
      name: "GitHub",
      enabled: true,
      ready: true,
    },
  });
  jest.spyOn(global, "fetch").mockImplementation(async (input) =>
    jsonResponse(
      String(input).endsWith("/preview")
        ? {
            ...skill,
            instructions_markdown: "Write a weekly report from these notes.",
          }
        : { builtins: [], customs: [skill] }
    )
  );
  show({
    kind: "external-app",
    app: memberApp({ authenticated: true }),
    connection: { kind: "connected", ownership: "user" },
  });
  const user = setupUser();
  await user.click(screen.getByRole("tab", { name: "Skills" }));
  await user.click(await screen.findByRole("switch"));
  const backdrop = document.querySelector(".opal-modal-overlay");
  const dialog = screen.getByRole("dialog");
  await user.click(screen.getByRole("button", { name: "Preview" }));
  expect(
    await screen.findByText("Write a weekly report from these notes.")
  ).toBeVisible();
  expect(screen.getAllByRole("dialog")).toEqual([dialog]);
  expect(document.querySelectorAll(".opal-modal-overlay")).toHaveLength(1);
  expect(document.querySelector(".opal-modal-overlay")).toBe(backdrop);
  expect(screen.queryByRole("tab", { name: "Skills" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Back" }));
  expect(screen.getByRole("tab", { name: "Skills" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  expect(await screen.findByRole("switch")).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  await user.click(screen.getByRole("button", { name: "Preview" }));
  await user.keyboard("{Escape}");
  expect(screen.getByRole("tab", { name: "Skills" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
});

test("skill saves disable conflicts first and retry only unsaved changes", async () => {
  const dependency = {
    external_app_id: 7,
    name: "GitHub",
    enabled: true,
    ready: true,
  };
  const replacement = customFixture({
    id: "replacement",
    enabled: false,
    external_app: dependency,
  });
  const previous = customFixture({
    id: "previous",
    enabled: true,
    external_app: dependency,
  });
  let failReplacement = true;
  const requests = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input, init) => {
      const path = String(input);
      if (path.includes("/action-policies/"))
        return jsonResponse({ ...approvalApp, actions: [] });
      if (init?.method === "PUT") {
        if (path.includes(replacement.id)) {
          return failReplacement
            ? jsonResponse({ detail: "Enable failed" }, 500)
            : jsonResponse({ ...replacement, enabled: true });
        }
        return jsonResponse({ ...previous, enabled: false });
      }
      return jsonResponse({ builtins: [], customs: [replacement, previous] });
    });
  const onClose = jest.fn();
  show(
    {
      kind: "external-app",
      app: memberApp({ authenticated: true }),
      connection: { kind: "connected", ownership: "user" },
    },
    jest.fn(),
    "craft",
    { onClose }
  );
  const user = setupUser();
  await user.click(screen.getByRole("tab", { name: "Skills" }));
  const enable = await screen.findByRole("switch", {
    name: "Enable report-writer",
  });
  const disable = screen.getByRole("switch", { name: "Disable report-writer" });
  await user.click(enable);
  await user.click(disable);
  await user.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Enable failed");
  expect(onClose).not.toHaveBeenCalled();
  expect(
    requests.mock.calls
      .filter(([, init]) => init?.method === "PUT")
      .map(([input]) => String(input))
  ).toEqual([
    "/api/skills/previous/enabled",
    "/api/skills/replacement/enabled",
  ]);
  failReplacement = false;
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  expect(
    requests.mock.calls
      .filter(([, init]) => init?.method === "PUT")
      .map(([input]) => String(input))
  ).toEqual([
    "/api/skills/previous/enabled",
    "/api/skills/replacement/enabled",
    "/api/skills/replacement/enabled",
  ]);
});

test("skill conflicts can be confirmed without losing remaining drafts", async () => {
  const dependency = {
    external_app_id: 7,
    name: "GitHub",
    enabled: true,
    ready: true,
  };
  const replacement = customFixture({
    id: "replacement",
    enabled: false,
    external_app: dependency,
  });
  const other = customFixture({
    id: "other",
    name: "another-skill",
    enabled: false,
    external_app: dependency,
  });
  const requests = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input, init) => {
      const path = String(input);
      if (path.includes("/action-policies/"))
        return jsonResponse({ ...approvalApp, actions: [] });
      if (init?.method === "PUT") {
        if (path.includes(replacement.id)) {
          const body = JSON.parse(String(init.body));
          return body.replace_conflict
            ? jsonResponse({ ...replacement, enabled: true })
            : jsonResponse(
                { detail: "Name conflict", error_code: "SKILL_NAME_CONFLICT" },
                409
              );
        }
        return jsonResponse({ ...other, enabled: true });
      }
      return jsonResponse({ builtins: [], customs: [replacement, other] });
    });
  const onClose = jest.fn();
  show(
    {
      kind: "external-app",
      app: memberApp({ authenticated: true }),
      connection: { kind: "connected", ownership: "user" },
    },
    jest.fn(),
    "craft",
    { onClose }
  );
  const user = setupUser();
  await user.click(screen.getByRole("tab", { name: "Skills" }));
  await user.click(
    await screen.findByRole("switch", { name: "Enable report-writer" })
  );
  await user.click(
    screen.getByRole("switch", { name: "Enable another-skill" })
  );
  const dialog = screen.getByRole("dialog");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByRole("button", { name: "Switch skill" });
  expect(screen.getByRole("dialog")).toBe(dialog);
  expect(onClose).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Back" }));
  expect(
    screen.getByRole("switch", { name: "Disable another-skill" })
  ).toBeChecked();
  await user.click(screen.getByRole("button", { name: "Save" }));
  await user.click(await screen.findByRole("button", { name: "Switch skill" }));
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  expect(requests).toHaveBeenCalledWith(
    "/api/skills/replacement/enabled",
    expect.objectContaining({
      body: JSON.stringify({ enabled: true, replace_conflict: true }),
    })
  );
  expect(requests).toHaveBeenCalledWith(
    "/api/skills/other/enabled",
    expect.objectContaining({
      body: JSON.stringify({ enabled: true, replace_conflict: false }),
    })
  );
});
