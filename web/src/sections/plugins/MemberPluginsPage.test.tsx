import { customFixture } from "@/lib/skills/__fixtures__/picker";
import type { SkillsList } from "@/lib/skills/types";
import { MCPConnectionStatus } from "@/lib/mcp/types";
import {
  act,
  deferred,
  render as renderWithProviders,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import MemberPluginsPage from "@/sections/plugins/MemberPluginsPage";
import {
  jsonResponse,
  memberServer,
  memberTool,
  storedMcpTool,
  memberApp,
  memberPluginMessages,
} from "@/sections/plugins/__tests__/memberPluginFixtures";
import { MCPAuthenticationPerformer, type MCPServer } from "@/lib/mcp/types";
import type { ToolSnapshot } from "@/lib/tools/types";
import type { ReactElement } from "react";
import { NextIntlClientProvider } from "next-intl";
import type { ExternalAppUserResponse } from "@/app/craft/v1/apps/registry";

function render(ui: ReactElement) {
  return renderWithProviders(
    <NextIntlClientProvider locale="en" messages={memberPluginMessages}>
      {ui}
    </NextIntlClientProvider>
  );
}

const mockPush = jest.fn();
const mockReplace = jest.fn();
let mockManage = false;
let mockSearchParams = new URLSearchParams();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
  useSearchParams: () => mockSearchParams,
  usePathname: () => "/app/plugins",
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({
    isGlobalHolder: mockManage,
    isScopedManager: false,
  }),
}));
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ onyx_craft_enabled: true }),
}));

function network({
  servers = [memberServer()],
  tools = [memberTool(), storedMcpTool],
  serverError = false,
  apps = [],
  appError = false,
  skills = { builtins: [], customs: [] },
}: {
  servers?: MCPServer[];
  tools?: ToolSnapshot[];
  serverError?: boolean;
  apps?: ExternalAppUserResponse[];
  appError?: boolean;
  skills?: SkillsList;
} = {}) {
  return jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    switch (String(input)) {
      case "/api/mcp/servers":
      case "/api/mcp/servers/craft":
        return jsonResponse(
          serverError
            ? { detail: "MCP unavailable" }
            : { mcp_servers: servers },
          serverError ? 503 : 200
        );
      case "/api/tool":
        return jsonResponse(tools);
      case "/api/user-oauth-token/status":
        return jsonResponse([]);
      case "/api/skills":
        return jsonResponse(skills);
      case "/api/build/apps/7/credentials":
        for (const app of apps) if (app.id === 7) app.authenticated = true;
        return jsonResponse({});
      case "/api/build/apps":
        return jsonResponse(
          appError ? { detail: "Apps unavailable" } : apps,
          appError ? 503 : 200
        );
      default:
        throw new Error(`Unexpected request ${String(input)}`);
    }
  });
}

beforeEach(() => {
  mockManage = false;
  mockPush.mockClear();
  mockSearchParams = new URLSearchParams();
});
afterEach(() => jest.restoreAllMocks());

test("connected cards use the status dot without an extra Connected line", async () => {
  network();
  render(<MemberPluginsPage />);
  await screen.findByRole("button", { name: "View Linear" });
  expect(screen.getAllByText("Connected")).toHaveLength(1);
  await setupUser().hover(
    screen.getByRole("button", { name: "Connection status for Linear" })
  );
  expect(await screen.findByRole("tooltip")).toHaveTextContent("Connected");
});

test("ordinary members see approved native plugins with colliding IDs without admin requests", async () => {
  const requests = network();
  render(<MemberPluginsPage />);
  expect(
    await screen.findByRole("button", { name: "View Linear" })
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "View Reports API" })
  ).toBeVisible();
  expect(screen.getByText("Chat only")).toBeVisible();
  expect(
    screen.queryByRole("link", { name: "Manage workspace plugins" })
  ).not.toBeInTheDocument();
  expect(requests.mock.calls.map(([url]) => String(url)).sort()).toEqual([
    "/api/build/apps",
    "/api/mcp/servers",
    "/api/tool",
    "/api/user-oauth-token/status",
  ]);
});

test("Needs sign-in includes only plugins needing personal connection", async () => {
  network({
    servers: [
      memberServer(),
      memberServer({
        id: 8,
        name: "Support MCP",
        connection_status: MCPConnectionStatus.NOT_CONNECTED,
      }),
    ],
  });
  render(<MemberPluginsPage initialFilter="needsSignIn" />);
  expect(
    await screen.findByRole("button", { name: "Connect Support MCP" })
  ).toBeVisible();
  expect(screen.queryByText("Connect your account")).not.toBeInTheDocument();
  expect(screen.queryByText("Add your credentials")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "View Linear" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "View Reports API" })
  ).not.toBeInTheDocument();
  expect(screen.queryByText("Sentry")).not.toBeInTheDocument();
});

test("management authority adds the workspace link without restricting member discovery", async () => {
  mockManage = true;
  network();
  render(<MemberPluginsPage />);
  expect(
    await screen.findByRole("button", { name: "View Linear" })
  ).toBeVisible();
  expect(
    screen.getByRole("link", { name: "Manage workspace plugins" })
  ).toHaveAttribute("href", "/admin/plugins");
});

test("search matches descriptions and URLs and can clear an empty result", async () => {
  network();
  render(<MemberPluginsPage />);
  await screen.findByRole("button", { name: "View Linear" });
  const user = setupUser();
  const search = screen.getByRole("textbox", { name: "Search plugins" });
  await user.type(search, "weekly");
  expect(
    screen.getByRole("button", { name: "View Reports API" })
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "View Linear" })
  ).not.toBeInTheDocument();
  await user.clear(search);
  await user.type(search, "mcp.linear.app");
  expect(screen.getByRole("button", { name: "View Linear" })).toBeVisible();
  await user.clear(search);
  await user.type(search, "missing");
  expect(screen.getByText("No matching plugins")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "View all plugins" }));
  expect(
    screen.getByRole("button", { name: "View Reports API" })
  ).toBeVisible();
});

test("a failed MCP source preserves OpenAPI plugins and exposes retry", async () => {
  const requests = network({ serverError: true });
  render(<MemberPluginsPage />);
  expect(
    await screen.findByRole("button", { name: "View Reports API" })
  ).toBeVisible();
  const error = await screen.findByRole("alert");
  expect(within(error).getByText("MCP plugins could not load.")).toBeVisible();
  await setupUser().click(within(error).getByRole("button", { name: "Retry" }));
  await waitFor(() =>
    expect(
      requests.mock.calls.filter(([url]) => url === "/api/mcp/servers")
    ).toHaveLength(2)
  );
});

test("pending account status stays checking instead of offering a missing-account connection", async () => {
  const pending = deferred<Response>();
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    if (String(input) === "/api/mcp/servers")
      return jsonResponse({ mcp_servers: [] });
    if (String(input) === "/api/tool")
      return jsonResponse([memberTool({ oauth_config_id: 9 })]);
    return pending.promise;
  });
  render(<MemberPluginsPage />);
  expect(await screen.findByText("Checking connection")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Connect Reports API" })
  ).not.toBeInTheDocument();
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Needs sign-in" }));
  expect(screen.queryByText("Checking connection")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /^All$/ }));
  expect(screen.getByText("Checking connection")).toBeVisible();
  await act(async () => pending.resolve(jsonResponse([])));
  expect(
    await screen.findByRole("button", { name: "Connect Reports API" })
  ).toBeVisible();
});

function expectDialogWheelAllowed() {
  const body = screen.getByRole("dialog").querySelector(".opal-modal-body");
  if (!(body instanceof HTMLElement)) throw new Error("Missing dialog body");
  // jsdom has no layout, but Radix's real scroll-lock listener still runs.
  body.style.overflowY = "auto";
  Object.defineProperties(body, {
    scrollHeight: { configurable: true, value: 1000 },
    clientHeight: { configurable: true, value: 200 },
  });
  const wheel = new WheelEvent("wheel", {
    bubbles: true,
    cancelable: true,
    deltaY: 100,
  });
  body.dispatchEvent(wheel);
  expect(wheel.defaultPrevented).toBe(false);
}

test("connecting from details replaces the detail dialog and dismissing leaves no dialog", async () => {
  network({
    servers: [
      memberServer({ connection_status: MCPConnectionStatus.NOT_CONNECTED }),
    ],
  });
  render(<MemberPluginsPage initialFilter="needsSignIn" />);
  const user = setupUser();
  await user.click(await screen.findByText("Linear"));
  expect(screen.getByRole("dialog", { name: /^Linear/ })).toBeVisible();
  const backdrop = document.querySelector(".opal-modal-overlay");
  expect(backdrop).not.toBeNull();
  expectDialogWheelAllowed();
  await user.click(screen.getByRole("button", { name: "Connect" }));
  expect(document.querySelectorAll(".opal-modal-overlay")).toHaveLength(1);
  expect(document.querySelector(".opal-modal-overlay")).toBe(backdrop);
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  expect(screen.getByRole("dialog", { name: /^Connect Linear/ })).toBeVisible();
  expectDialogWheelAllowed();
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("plugin details use Cancel and Save without navigating to Chat or Craft", async () => {
  network();
  render(<MemberPluginsPage />);
  const user = setupUser();
  await user.click(await screen.findByRole("button", { name: "View Linear" }));
  const dialog = screen.getByRole("dialog");
  expect(
    within(dialog).queryByRole("button", { name: /Use in Chat|Open in Craft/ })
  ).not.toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: "Save" })).toBeDisabled();
  await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(mockPush).not.toHaveBeenCalled();
});

test("All keeps connected, missing, checking, unavailable, and workspace-setup entries in one list", async () => {
  network({
    servers: [
      memberServer(),
      memberServer({
        id: 8,
        name: "Needs account",
        connection_status: MCPConnectionStatus.NOT_CONNECTED,
      }),
      memberServer({
        id: 9,
        name: "Unknown account",
        connection_status: null,
      }),
      memberServer({
        id: 10,
        name: "Workspace setup",
        connection_status: MCPConnectionStatus.NOT_CONNECTED,
        auth_performer: MCPAuthenticationPerformer.ADMIN,
      }),
    ],
    apps: [memberApp()],
  });
  render(<MemberPluginsPage />);
  expect(await screen.findByText("Workspace GitHub")).toBeVisible();
  expect(screen.getByText("Needs account")).toBeVisible();
  expect(screen.getByText("Unknown account")).toBeVisible();
  expect(screen.getByText("Workspace setup")).toBeVisible();
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Needs sign-in" }));
  expect(screen.queryByText("Unknown account")).not.toBeInTheDocument();
  expect(screen.queryByText("Workspace setup")).not.toBeInTheDocument();
  expect(screen.queryByText("Linear")).not.toBeInTheDocument();
  expect(screen.getByText("Workspace GitHub")).toBeVisible();
  await user.click(screen.getByRole("button", { name: /^Connected$/ }));
  expect(screen.getByText("Linear")).toBeVisible();
  expect(screen.queryByText("Needs account")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /^All$/ }));
  expect(screen.getByText("Unknown account")).toBeVisible();
});

test("Craft lists Craft MCP and enabled apps, without OpenAPI or Chat-only MCP", async () => {
  const requests = network({
    servers: [
      memberServer({ craft_connected: true }),
      memberServer({ id: 8, name: "Chat only MCP", available_in_craft: false }),
    ],
    apps: [memberApp()],
  });
  render(<MemberPluginsPage surface="craft" />);
  expect(await screen.findByText("Workspace GitHub")).toBeVisible();
  expect(screen.getByText("Linear")).toBeVisible();
  expect(screen.queryByText("Reports API")).not.toBeInTheDocument();
  expect(screen.queryByText("Chat only MCP")).not.toBeInTheDocument();
  expect(requests.mock.calls.map(([url]) => String(url)).sort()).toEqual([
    "/api/build/apps",
    "/api/mcp/servers/craft",
  ]);
});

test("legacy connect links select an external app despite colliding MCP IDs", async () => {
  network({ apps: [memberApp()] });
  mockSearchParams = new URLSearchParams({ connect: "7" });
  render(<MemberPluginsPage surface="craft" />);
  expect(
    await screen.findByRole("dialog", { name: /^Connect Workspace GitHub/ })
  ).toBeVisible();
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  expect(
    screen.queryByRole("dialog", { name: /^Connect Linear/ })
  ).not.toBeInTheDocument();
});

test("a legacy connection link can reopen after navigating away from its query", async () => {
  network({ apps: [memberApp()] });
  mockSearchParams = new URLSearchParams({ connect: "7" });
  function page() {
    return (
      <NextIntlClientProvider locale="en" messages={memberPluginMessages}>
        <MemberPluginsPage surface="craft" />
      </NextIntlClientProvider>
    );
  }
  const view = renderWithProviders(page());
  const first = await screen.findByRole("dialog", {
    name: /^Connect Workspace GitHub/,
  });
  await setupUser().click(
    within(first).getByRole("button", { name: "Cancel" })
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  mockSearchParams = new URLSearchParams();
  view.rerender(page());
  mockSearchParams = new URLSearchParams({ connect: "7" });
  view.rerender(page());
  expect(
    await screen.findByRole("dialog", { name: /^Connect Workspace GitHub/ })
  ).toBeVisible();
});

test("Craft MCP details omit unavailable Chat metadata and use the settings footer", async () => {
  network({
    servers: [
      memberServer({ craft_connected: true, default_chat_enabled: undefined }),
    ],
  });
  render(<MemberPluginsPage surface="craft" />);
  const user = setupUser();
  await user.click(await screen.findByRole("button", { name: "View Linear" }));
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).queryByText("Main Chat")).not.toBeInTheDocument();
  expect(within(dialog).getByRole("tab", { name: "Tools" })).toBeVisible();
  expect(
    within(dialog).queryByText(/No tools|Chat availability/i)
  ).not.toBeInTheDocument();
  expect(
    within(dialog).queryByRole("button", { name: "Use in Chat" })
  ).not.toBeInTheDocument();
  expect(
    within(dialog).queryByRole("button", { name: "Open in Craft" })
  ).not.toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: "Save" })).toBeDisabled();
  await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(mockPush).not.toHaveBeenCalled();
});

test("external app details show tools and the settings footer", async () => {
  network({ apps: [memberApp({ authenticated: true })] });
  render(<MemberPluginsPage />);
  const user = setupUser();
  await user.click(
    await screen.findByRole("button", { name: "View Workspace GitHub" })
  );
  const dialog = screen.getByRole("dialog");
  expect(
    within(dialog).queryByRole("button", { name: "Use in Chat" })
  ).not.toBeInTheDocument();
  expect(within(dialog).getByRole("tab", { name: "Tools" })).toBeVisible();
  expect(
    within(dialog).queryByRole("button", { name: "Open in Craft" })
  ).not.toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: "Save" })).toBeDisabled();
  await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(mockPush).not.toHaveBeenCalled();
});

test("external app source errors preserve available MCP and OpenAPI rows", async () => {
  network({ appError: true });
  render(<MemberPluginsPage />);
  expect(await screen.findByText("Craft apps could not load.")).toBeVisible();
  expect(screen.getByText("Linear")).toBeVisible();
  expect(screen.getByText("Reports API")).toBeVisible();
});

test("pending external apps expose their own loader while native rows remain available", async () => {
  const pending = deferred<Response>();
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    if (String(input) === "/api/build/apps") return pending.promise;
    if (String(input) === "/api/mcp/servers")
      return jsonResponse({ mcp_servers: [memberServer()] });
    return jsonResponse([]);
  });
  render(<MemberPluginsPage />);
  expect(await screen.findByText("Linear")).toBeVisible();
  expect(
    screen.getByRole("status", { name: "Loading Craft apps" })
  ).toBeVisible();
  await act(async () => pending.resolve(jsonResponse([])));
  expect(
    screen.queryByRole("status", { name: "Loading Craft apps" })
  ).not.toBeInTheDocument();
});

test("connecting an app keeps its row in the default All filter", async () => {
  const app = memberApp({
    supports_oauth: false,
    credential_keys: ["api_key"],
  });
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    const path = String(input);
    if (path === "/api/build/apps/7/credentials") {
      app.authenticated = true;
      return jsonResponse({});
    }
    if (path === "/api/build/apps") return jsonResponse([app]);
    if (path === "/api/mcp/servers") return jsonResponse({ mcp_servers: [] });
    return jsonResponse([]);
  });
  render(<MemberPluginsPage />);
  const user = setupUser();
  await user.click(
    await screen.findByRole("button", { name: "Connect Workspace GitHub" })
  );
  await user.type(screen.getByLabelText("api_key"), "personal-key");
  await user.click(screen.getByRole("button", { name: /^Connect$/ }));
  const details = await screen.findByRole("dialog", {
    name: /^Workspace GitHub/,
  });
  await user.click(within(details).getByRole("tab", { name: "Connection" }));
  expect(within(details).getByRole("status")).toHaveTextContent("Connected");
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  await user.click(within(details).getByRole("button", { name: /^Cancel$/ }));
  expect(
    screen.getByRole("button", { name: "View Workspace GitHub" })
  ).toBeVisible();
  expect(screen.getByRole("button", { name: /^All$/ })).toHaveAttribute(
    "aria-pressed",
    "true"
  );
});

test("closes an approval deep link without reopening or dropping other parameters", async () => {
  network({ apps: [memberApp({ authenticated: true })] });
  mockSearchParams = new URLSearchParams({
    actionPolicies: "app-7",
    returnTo: "/app?chatId=42",
  });
  render(<MemberPluginsPage />);
  const user = setupUser();
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByRole("tab", { name: "Tools" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(mockReplace).toHaveBeenCalledWith(
    "/app/plugins?returnTo=%2Fapp%3FchatId%3D42",
    { scroll: false }
  );
});

test.each([true, false])(
  "external app status reflects associated skill enablement (%s)",
  async (enabled) => {
    network({
      apps: [memberApp({ authenticated: true, name: "GitHub" })],
      skills: {
        builtins: [],
        customs: [
          customFixture({
            enabled,
            external_app: {
              external_app_id: 7,
              name: "GitHub",
              enabled: true,
              ready: true,
            },
          }),
        ],
      },
    });
    render(<MemberPluginsPage />);
    const indicator = await screen.findByRole("button", {
      name: "Connection status for GitHub",
    });
    await waitFor(() =>
      expect(indicator.querySelector("span[aria-hidden]")).toHaveClass(
        enabled ? "bg-status-success-05" : "bg-status-warning-05"
      )
    );
    await setupUser().hover(indicator);
    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      enabled ? "Connected" : "Not all associated skills are enabled."
    );
    expect(screen.getByText("Craft App")).toBeVisible();
  }
);

test("a successful connection returns to the Connection tab with the same backdrop", async () => {
  const app = memberApp({
    supports_oauth: false,
    credential_keys: ["api_key"],
  });
  network({ apps: [app] });
  render(<MemberPluginsPage />);
  const user = setupUser();
  await user.click(
    await screen.findByRole("button", { name: "Connect Workspace GitHub" })
  );
  const backdrop = document.querySelector(".opal-modal-overlay");
  await user.type(screen.getByLabelText("api_key"), "test-key");
  await user.click(screen.getByRole("button", { name: "Connect" }));
  expect(
    await screen.findByRole("tab", { name: "Connection" })
  ).toHaveAttribute("aria-selected", "true");
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveTextContent("Connected")
  );
  expect(document.querySelector(".opal-modal-overlay")).toBe(backdrop);
});
