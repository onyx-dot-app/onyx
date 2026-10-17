import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import PluginAddCatalogModal from "@/sections/plugins/PluginAddCatalogModal";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  BuiltInExternalAppDescriptor,
  ExternalAppAdminResponse,
} from "@/app/craft/v1/apps/registry";
import { SUGGESTED_MCP_PLUGINS } from "@/lib/plugins/catalog";

let mockFullAdmin = true;
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({ isGlobalHolder: mockFullAdmin }),
}));

const slack: BuiltInExternalAppDescriptor = {
  app_type: "SLACK",
  name: "Slack",
  upstream_url_patterns: ["https://slack.com/api/*"],
  auth_template: {},
  required_org_credential_fields: [],
  setup_instructions: "",
  actions: [],
};

function showCatalog(kind: "mcp" | "external-app", canManageActions = true) {
  const onPick = jest.fn();
  const onClose = jest.fn();
  render(
    <PluginAddCatalogModal
      catalogKind={kind}
      canManageActions={canManageActions}
      installedEndpoints={new Set(["https://mcp.linear.app/mcp"])}
      onPick={onPick}
      onClose={onClose}
    />,
    {
      swrConfig: {
        fallback: {
          [SWR_KEYS.buildExternalAppsBuiltInOptions]: [slack],
          [SWR_KEYS.buildExternalAppsAdmin]: [],
        },
        revalidateOnMount: false,
      },
    }
  );
  return { onPick, onClose };
}

beforeEach(() => {
  mockFullAdmin = true;
});
afterEach(() => jest.restoreAllMocks());

test("installed-app failure offers retry and custom creation, then excludes installed providers after recovery", async () => {
  const github: BuiltInExternalAppDescriptor = {
    ...slack,
    app_type: "GITHUB",
    name: "GitHub",
  };
  const installedSlack: ExternalAppAdminResponse = {
    id: 7,
    name: "Workspace Slack",
    app_type: "SLACK",
    enabled: true,
    upstream_url_patterns: [],
    auth_template: {},
    organization_credentials: {},
    credential_placeholder_keys: [],
    actions: [],
    associated_skills: [],
    is_onyx_managed: false,
  };
  let installedRequestCount = 0;
  const network = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) => {
      if (String(input) === SWR_KEYS.buildExternalAppsAdmin) {
        installedRequestCount += 1;
        return installedRequestCount === 1
          ? new Response(JSON.stringify({ detail: "Unavailable" }), {
              status: 503,
            })
          : new Response(JSON.stringify([installedSlack]));
      }
      return new Response(JSON.stringify([slack, github]));
    });
  const onPick = jest.fn();
  render(
    <PluginAddCatalogModal
      catalogKind="external-app"
      canManageActions
      installedEndpoints={new Set()}
      onPick={onPick}
      onClose={jest.fn()}
    />
  );
  const user = setupUser();
  expect(await screen.findByText("Apps could not load")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Add Slack" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Add GitHub" })).toBeNull();
  expect(screen.queryByRole("status", { name: "Loading" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Custom app" }));
  expect(onPick).toHaveBeenLastCalledWith({ kind: "external-app" });
  await user.click(screen.getByRole("button", { name: "Retry" }));
  await user.click(await screen.findByRole("button", { name: "Add GitHub" }));
  expect(onPick).toHaveBeenLastCalledWith({
    kind: "external-app",
    descriptor: github,
  });
  expect(screen.queryByRole("button", { name: "Add Slack" })).toBeNull();
  expect(screen.queryByText("Apps could not load")).toBeNull();
  await waitFor(() => {
    expect(
      network.mock.calls.filter(
        ([input]) => String(input) === SWR_KEYS.buildExternalAppsAdmin
      )
    ).toHaveLength(2);
    expect(
      network.mock.calls.filter(
        ([input]) => String(input) === SWR_KEYS.buildExternalAppsBuiltInOptions
      )
    ).toHaveLength(2);
  });
});

test("custom creation stays usable while the installed-app list is pending", async () => {
  jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) =>
      String(input) === SWR_KEYS.buildExternalAppsAdmin
        ? new Promise<Response>(() => {})
        : new Response(JSON.stringify([slack]))
    );
  const onPick = jest.fn();
  render(
    <PluginAddCatalogModal
      catalogKind="external-app"
      canManageActions
      installedEndpoints={new Set()}
      onPick={onPick}
      onClose={jest.fn()}
    />
  );
  expect(screen.getByRole("status", { name: "Loading" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Add Slack" })).toBeNull();
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Custom app" }));
  expect(onPick).toHaveBeenCalledWith({ kind: "external-app" });
});

test.each(["mcp", "external-app"] as const)(
  "%s uses the shared top anchor and peer grid cards",
  (kind) => {
    showCatalog(kind);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("data-position", "top");
    expect(dialog).toHaveAttribute("data-width", "lg");
    expect(dialog.querySelector(".opal-modal-body")).toHaveAttribute(
      "data-two-tone"
    );
    const custom = within(dialog).getByRole("button", {
      name: kind === "mcp" ? "Add custom MCP server" : "Custom app",
    });
    const provider = within(dialog).getByRole("button", { name: "Add Slack" });
    expect(custom.parentElement).toBe(provider.parentElement);
    expect(custom.parentElement).toHaveClass("grid", "md:grid-cols-2");
    expect(custom.className).toBe(provider.className);
  }
);

test("MCP providers and custom cards select their own flows and omit installed servers", async () => {
  const user = setupUser();
  const { onPick } = showCatalog("mcp");
  expect(screen.queryByRole("button", { name: "Add Linear" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Add Slack" }));
  expect(onPick).toHaveBeenLastCalledWith({
    kind: "mcp",
    suggestion: SUGGESTED_MCP_PLUGINS[0],
  });
  await user.click(
    screen.getByRole("button", { name: "Add custom MCP server" })
  );
  expect(onPick).toHaveBeenLastCalledWith({ kind: "mcp" });
});

test("app providers and custom cards share keyboard activation", async () => {
  const user = setupUser();
  const { onPick } = showCatalog("external-app");
  screen.getByRole("button", { name: "Add Slack" }).focus();
  await user.keyboard("{Enter}");
  expect(onPick).toHaveBeenLastCalledWith({
    kind: "external-app",
    descriptor: slack,
  });
  screen.getByRole("button", { name: "Custom app" }).focus();
  await user.keyboard(" ");
  expect(onPick).toHaveBeenLastCalledWith({ kind: "external-app" });
  expect(screen.queryByRole("button", { name: "Create" })).toBeNull();
});

test.each([
  { kind: "external-app", fullAdmin: false },
  { kind: "mcp", fullAdmin: true },
] as const)(
  "$kind does not fetch external app data with fullAdmin=$fullAdmin",
  ({ kind, fullAdmin }) => {
    mockFullAdmin = fullAdmin;
    const fetchSpy = jest.spyOn(global, "fetch");
    render(
      <PluginAddCatalogModal
        catalogKind={kind}
        canManageActions
        installedEndpoints={new Set()}
        onPick={jest.fn()}
        onClose={jest.fn()}
      />
    );
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Custom app" })).toBeNull();
    if (kind === "mcp")
      expect(screen.getByRole("button", { name: "Add Slack" })).toBeVisible();
    else expect(screen.queryByRole("button", { name: "Add Slack" })).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
  }
);

test("MCP discovery does not expose creation cards without action management", () => {
  showCatalog("mcp", false);
  expect(
    screen.queryByRole("button", { name: "Add custom MCP server" })
  ).toBeNull();
});
