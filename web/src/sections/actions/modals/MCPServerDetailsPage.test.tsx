jest.mock("next/navigation", () => ({
  ...jest.requireActual("next/navigation"),
  useRouter: () => ({ push: jest.fn() }),
}));

import { Form, Formik } from "formik";
import { Button, useCreateModal } from "@opal/components";
import {
  act,
  deferred,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import MCPServerDetailsPage, {
  MCPAccessControl,
  type MCPServerFormValues,
  validateMCPAccess,
} from "@/sections/actions/modals/MCPServerDetailsPage";
import MCPServerSetupModal from "@/sections/actions/modals/MCPServerSetupModal";
import { renderHook } from "@testing-library/react";
import * as UserProvider from "@/providers/UserProvider";
import { Permission } from "@/lib/types";
import { MCPServerStatus, type MCPServer } from "@/lib/mcp/types";
import messages from "@/i18n/messages/en.json";
import { Tier } from "@/lib/tiers/types";

jest.mock("@/providers/UserProvider", () => {
  const actual = jest.requireActual<typeof UserProvider>(
    "@/providers/UserProvider"
  );
  return { ...actual, useUser: jest.fn(actual.useUser) };
});

const initialValues: MCPServerFormValues = {
  name: "Example MCP",
  server_url: "https://example.com/mcp",
  access_mode: "groups",
  is_public: false,
  groups: [1],
  users: ["existing-user"],
};

function renderAccess({
  values = initialValues,
  scoped = false,
  canRestrict = true,
}: {
  values?: MCPServerFormValues;
  scoped?: boolean;
  canRestrict?: boolean;
} = {}) {
  const submit = jest.fn();
  render(
    <Formik
      initialValues={values}
      validate={(value) =>
        validateMCPAccess(value, scoped, "Choose at least one group")
      }
      onSubmit={submit}
    >
      <Form>
        <MCPAccessControl
          isGlobalHolder={!scoped}
          isScopedManager={scoped}
          canRestrict={canRestrict}
        />
        <Button type="submit">Save access</Button>
      </Form>
    </Formik>
  );
  return submit;
}

let saveResponse: () => Promise<Response>;
let serverDetailsResponse: (() => Promise<Response>) | undefined;
let authResponse: (() => Promise<Response>) | undefined;
let settingsResponse: (() => Promise<Response>) | undefined;
let savedRequests: {
  url: string;
  method: string | undefined;
  payload: unknown;
}[];

let serverRecord: MCPServer;
let discoveryRequests: string[];

let availableGroups: { id: number; name: string; users: never[] }[];

beforeEach(() => {
  jest
    .mocked(UserProvider.useUser)
    .mockImplementation(
      jest.requireActual<typeof UserProvider>("@/providers/UserProvider")
        .useUser
    );
  savedRequests = [];
  serverRecord = configuredServer;
  discoveryRequests = [];
  settingsResponse = undefined;
  authResponse = undefined;
  serverDetailsResponse = undefined;
  saveResponse = async () => new Response(JSON.stringify(serverRecord));
  availableGroups = [
    { id: 1, name: "Engineering", users: [] },
    { id: 2, name: "Support", users: [] },
  ];
  jest.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === "/api/admin/mcp/servers/7")
      return serverDetailsResponse
        ? serverDetailsResponse()
        : new Response(JSON.stringify(serverRecord));
    if (url === "/api/auth/type")
      return new Response(
        JSON.stringify({ auth_type: "basic", oauth_enabled: false })
      );
    if (url === "/api/admin/mcp/oauth/discover") {
      discoveryRequests.push(serverRecord.server_url);
      return new Response(
        JSON.stringify({
          status: "metadata_found",
          supports_automatic_registration: true,
          authorization_endpoint: "https://identity.example.com/authorize",
          token_endpoint: "https://identity.example.com/token",
        })
      );
    }
    if (url.includes("/status")) return new Response("{}");
    if (url === "/api/admin/mcp/servers/create") {
      savedRequests.push({
        url,
        method: init?.method,
        payload: JSON.parse(String(init?.body)),
      });
      return authResponse
        ? authResponse()
        : new Response(JSON.stringify({ server_id: 7 }));
    }
    if (url === "/api/admin/mcp/server/7/tools/snapshots")
      return new Response("[]");
    if (url.startsWith("/api/admin/mcp/server")) {
      savedRequests.push({
        url,
        method: init?.method,
        payload: JSON.parse(String(init?.body)),
      });
      const payload: unknown = JSON.parse(String(init?.body));
      if (payload && typeof payload === "object") {
        serverRecord = { ...serverRecord };
        if ("name" in payload && typeof payload.name === "string")
          serverRecord.name = payload.name;
        if ("server_url" in payload && typeof payload.server_url === "string")
          serverRecord.server_url = payload.server_url;
        if ("description" in payload && typeof payload.description === "string")
          serverRecord.description = payload.description;
      }
      return saveResponse();
    }
    if (url === "/api/settings" && settingsResponse) return settingsResponse();
    // Settings enable the real group picker without mocking application hooks.
    if (url === "/api/settings")
      return new Response(
        JSON.stringify({ tier: Tier.BUSINESS, ee_features_enabled: true })
      );
    if (url === "/api/enterprise-settings") return new Response("{}");
    if (url === "/api/manage/admin/user-group")
      return new Response(JSON.stringify(availableGroups));
    throw new Error(`Unexpected request: ${url}`);
  });
});

afterEach(() => jest.restoreAllMocks());

test("Public is the only alternative to groups and clears explicit grants", async () => {
  const submit = renderAccess();
  const user = setupUser();
  await user.click(screen.getByRole("combobox", { name: "Access control" }));
  expect(screen.getAllByRole("option")).toHaveLength(2);
  expect(
    screen.queryByRole("option", { name: /^Private/ })
  ).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("option", {
      name: /^Public Anyone in your organization can use this MCP/,
    })
  );
  await user.click(screen.getByRole("button", { name: "Save access" }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(submit.mock.calls[0]?.[0]).toEqual(
    expect.objectContaining({ is_public: true, groups: [], users: [] })
  );
});

test("adding a group preserves existing direct-user grants", async () => {
  const submit = renderAccess();
  const user = setupUser();
  await screen.findByText("Engineering");
  const groupPicker = screen.getByPlaceholderText("Add user groups");
  await user.click(groupPicker);
  await user.click(await screen.findByRole("option", { name: /^Support/ }));
  await user.click(screen.getByRole("button", { name: "Save access" }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(submit.mock.calls[0]?.[0]).toEqual(
    expect.objectContaining({
      is_public: false,
      groups: [1, 2],
      users: ["existing-user"],
    })
  );
});

test("scoped managers can select groups only and must choose a group", async () => {
  const submit = renderAccess({
    scoped: true,
    values: { ...initialValues, groups: [] },
  });
  const user = setupUser();
  await user.click(screen.getByRole("combobox", { name: "Access control" }));
  expect(
    screen.queryByRole("option", { name: /^Public/ })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("option", { name: /^Private/ })
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("option", { name: /^User groups/ }));
  await user.click(screen.getByRole("button", { name: "Save access" }));
  expect(
    await screen.findByText("Choose at least one group")
  ).toBeInTheDocument();
  expect(submit).not.toHaveBeenCalled();
  const picker = screen.getByPlaceholderText("Add user groups");
  await waitFor(() => expect(picker).toBeEnabled());
  await user.click(picker);
  await user.click(await screen.findByRole("option", { name: /^Engineering/ }));
  await user.click(screen.getByRole("button", { name: "Save access" }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(submit.mock.calls[0]?.[0]).toEqual(
    expect.objectContaining({ is_public: false, groups: [1] })
  );
});

test("restricted access options stay locked below the Business plan", async () => {
  renderAccess({
    canRestrict: false,
    values: {
      ...initialValues,
      access_mode: "public",
      is_public: true,
      groups: [],
      users: [],
    },
  });
  const user = setupUser();
  await user.click(screen.getByRole("combobox", { name: "Access control" }));
  expect(screen.getByRole("option", { name: /^User groups/ })).toHaveAttribute(
    "aria-disabled",
    "true"
  );
});

test("keeps 50 selected groups editable and preserves the remaining grants when removing a pill", async () => {
  availableGroups = Array.from({ length: 51 }, (_, index) => ({
    id: index + 1,
    name: `Group ${index + 1}`,
    users: [],
  }));
  const submit = renderAccess({
    values: {
      ...initialValues,
      groups: availableGroups.slice(0, 50).map((group) => group.id),
    },
  });
  const user = setupUser();
  await screen.findByRole("button", { name: "Remove Group 50" });
  const selectedGroups = screen.getByRole("group", { name: "User groups" });
  expect(
    within(selectedGroups).getAllByRole("button", { name: /^Remove Group / })
  ).toHaveLength(50);
  expect(selectedGroups).not.toContainElement(
    screen.getByPlaceholderText("Add user groups")
  );
  await user.click(screen.getByRole("button", { name: "Remove Group 1" }));
  expect(
    screen.queryByRole("button", { name: "Remove Group 1" })
  ).not.toBeInTheDocument();
  const picker = screen.getByPlaceholderText("Add user groups");
  await user.type(picker, "Group 51");
  await user.click(await screen.findByRole("option", { name: /^Group 51/ }));
  await user.click(screen.getByRole("button", { name: "Save access" }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(submit.mock.calls[0]?.[0]).toEqual(
    expect.objectContaining({
      groups: availableGroups.slice(1).map((group) => group.id),
      users: ["existing-user"],
      is_public: false,
    })
  );
});

const configuredServer: MCPServer = {
  id: 7,
  name: "Example MCP",
  server_url: "https://example.com/mcp",
  description: "Tools for support",
  owner: "admin@example.com",
  status: MCPServerStatus.CREATED,
  is_public: true,
  groups: [],
  users: [],
  tool_count: 0,
};

function ModalHarness({
  server = null,
  created,
  refresh,
  editOnly,
}: {
  server?: MCPServer | null;
  editOnly: boolean;
  created: (server: MCPServer) => void;
  refresh: () => Promise<void>;
}) {
  const modal = useCreateModal();
  return (
    <>
      <Button onClick={() => modal.toggle(true)}>Open server</Button>
      <modal.Provider>
        <MCPServerSetupModal
          server={server}
          editOnly={editOnly}
          onServerSaved={created}
          onTriggerFetchTools={async () => {}}
          mutateMcpServers={refresh}
        />
      </modal.Provider>
    </>
  );
}

async function openServerModal(
  server: MCPServer | null = null,
  editOnly = Boolean(server)
) {
  if (server) serverRecord = server;
  const context = renderHook(() => UserProvider.useUser());
  const base = context.result.current;
  context.unmount();
  jest
    .mocked(UserProvider.useUser)
    .mockReturnValue({ ...base, permissions: [Permission.MANAGE_ACTIONS] });
  const created = jest.fn();
  const refresh = jest.fn().mockResolvedValue(undefined);
  render(
    <ModalHarness
      server={server}
      created={created}
      refresh={refresh}
      editOnly={editOnly}
    />
  );
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Open server" }));
  return { user, created, refresh };
}

test("creates a public server and opens authentication within the same dialog", async () => {
  const { user, created, refresh } = await openServerModal();
  await user.type(
    await screen.findByRole("textbox", { name: "Server Name" }),
    "Example MCP"
  );
  await user.type(
    screen.getByRole("textbox", { name: /^MCP Server URL/ }),
    configuredServer.server_url
  );
  const dialog = screen.getByRole("dialog");
  await user.click(
    screen.getByRole("button", { name: messages.actions.mcpSetup.continue })
  );
  await waitFor(() =>
    expect(created).toHaveBeenCalledWith(
      expect.objectContaining({ id: 7, name: "Example MCP" })
    )
  );
  expect(refresh).toHaveBeenCalledTimes(1);
  expect(savedRequests).toEqual([
    {
      url: "/api/admin/mcp/server",
      method: "POST",
      payload: {
        name: "Example MCP",
        server_url: configuredServer.server_url,
        available_in_craft: false,
        description: "",
        is_public: true,
        groups: [],
        users: [],
      },
    },
  ]);
  expect(screen.getByRole("dialog")).toBe(dialog);
  expect(await screen.findByRole("tab", { name: "OAuth" })).toBeVisible();
});

test("edits an existing server without creating another or dropping restricted grants", async () => {
  const { user, created, refresh } = await openServerModal({
    ...configuredServer,
    is_public: false,
    groups: [1],
    users: ["existing-user"],
  });
  const name = await screen.findByRole("textbox", { name: "Server Name" });
  expect(name).toHaveValue("Example MCP");
  expect(screen.getByRole("button", { name: "Save Changes" })).toBeDisabled();
  await user.clear(name);
  await user.type(name, "Updated MCP");
  await user.click(screen.getByRole("button", { name: "Save Changes" }));
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  expect(created).toHaveBeenCalledWith(
    expect.objectContaining({ name: "Updated MCP" })
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  );
  expect(savedRequests).toEqual([
    {
      url: "/api/admin/mcp/server/7",
      method: "PATCH",
      payload: expect.objectContaining({
        name: "Updated MCP",
        is_public: false,
        groups: [1],
        users: ["existing-user"],
      }),
    },
  ]);
});

test("keeps edits after a failed save and permits retry", async () => {
  saveResponse = async () =>
    new Response("Provider is unavailable", { status: 503 });
  const { user, refresh } = await openServerModal(configuredServer);
  await user.type(
    await screen.findByRole("textbox", { name: "Server Name" }),
    " updated"
  );
  await user.click(screen.getByRole("button", { name: "Save Changes" }));
  await waitFor(() => expect(savedRequests).toHaveLength(1));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save Changes" })).toBeEnabled()
  );
  expect(screen.getByRole("textbox", { name: "Server Name" })).toHaveValue(
    "Example MCP updated"
  );
  expect(refresh).not.toHaveBeenCalled();
  saveResponse = async () => new Response(JSON.stringify(serverRecord));
  await user.click(screen.getByRole("button", { name: "Save Changes" }));
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  expect(savedRequests).toHaveLength(2);
});

test("blocks invalid input and waits for permissions before exposing the form", async () => {
  const settings = deferred<Response>();
  settingsResponse = () => settings.promise;
  const { user } = await openServerModal();
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(
    screen.queryByRole("textbox", { name: "Server Name" })
  ).not.toBeInTheDocument();
  await act(async () =>
    settings.resolve(
      new Response(
        JSON.stringify({ tier: Tier.BUSINESS, ee_features_enabled: true })
      )
    )
  );
  await user.type(
    await screen.findByRole("textbox", { name: "Server Name" }),
    "Invalid MCP"
  );
  await user.type(
    screen.getByRole("textbox", { name: /^MCP Server URL/ }),
    "invalid-url"
  );
  await user.tab();
  expect(
    screen.getByRole("button", { name: messages.actions.mcpSetup.continue })
  ).toBeDisabled();
  expect(savedRequests).toHaveLength(0);
});

test("keeps the form open during save despite Escape and header close", async () => {
  const pending = deferred<Response>();
  saveResponse = () => pending.promise;
  const { user, refresh } = await openServerModal({
    ...configuredServer,
    status: MCPServerStatus.CONNECTED,
    user_can_authenticate: true,
  });
  await user.type(
    await screen.findByRole("textbox", { name: "Server Name" }),
    " updated"
  );
  await user.click(screen.getByRole("button", { name: "Save Changes" }));
  await waitFor(() => expect(savedRequests).toHaveLength(1));
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  await user.keyboard("{Escape}");
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  await act(async () =>
    pending.resolve(new Response(JSON.stringify(configuredServer)))
  );
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  );
});

test("Back preserves drafts for the same URL and changing URL resets authentication before rediscovery", async () => {
  const { user } = await openServerModal(configuredServer, false);
  const dialog = screen.getByRole("dialog");
  await user.click(
    await screen.findByRole("button", {
      name: messages.actions.mcpSetup.continue,
    })
  );
  await user.click(
    await screen.findByRole("tab", { name: "Use your own OAuth client" })
  );
  await user.type(
    screen.getByRole("textbox", { name: /^Client ID/ }),
    "draft-client"
  );
  await user.click(
    screen.getByRole("button", { name: messages.actions.mcpSetup.back })
  );
  const name = await screen.findByRole("textbox", { name: "Server Name" });
  expect(name).toHaveValue(configuredServer.name);
  await user.clear(name);
  await user.type(name, "Updated analytics");
  await user.click(
    screen.getByRole("button", { name: messages.actions.mcpSetup.continue })
  );
  expect(
    await screen.findByRole("textbox", { name: /^Client ID/ })
  ).toHaveValue("draft-client");
  await user.click(
    screen.getByRole("button", { name: messages.actions.mcpSetup.back })
  );
  const url = screen.getByRole("textbox", { name: /^MCP Server URL/ });
  await user.clear(url);
  await user.type(url, "https://updated.example.com/mcp");
  await user.click(
    screen.getByRole("button", { name: messages.actions.mcpSetup.continue })
  );
  expect(
    await screen.findByRole("tab", { name: "Set up automatically" })
  ).toHaveAttribute("aria-selected", "true");
  await user.click(
    screen.getByRole("tab", { name: "Use your own OAuth client" })
  );
  expect(screen.getByRole("textbox", { name: /^Client ID/ })).toHaveValue("");
  expect(screen.getByRole("dialog")).toBe(dialog);
  await waitFor(() =>
    expect(discoveryRequests).toContain("https://updated.example.com/mcp")
  );
  expect(discoveryRequests).toContain(configuredServer.server_url);
  await user.click(screen.getByRole("tab", { name: "No authentication" }));
  await user.click(screen.getByTestId("mcp-auth-connect-button"));
  await waitFor(() =>
    expect(savedRequests).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          url: "/api/admin/mcp/servers/create",
          payload: expect.objectContaining({
            name: "Updated analytics",
            server_url: "https://updated.example.com/mcp",
          }),
        }),
      ])
    )
  );
});

test("locks Back, page navigation, and Escape while authentication is saving", async () => {
  const pending = deferred<Response>();
  authResponse = () => pending.promise;
  const { user } = await openServerModal(configuredServer, false);
  await user.click(
    await screen.findByRole("button", {
      name: messages.actions.mcpSetup.continue,
    })
  );
  await user.click(
    await screen.findByRole("tab", { name: "No authentication" })
  );
  await user.click(screen.getByTestId("mcp-auth-connect-button"));
  await waitFor(() =>
    expect(
      savedRequests.some(({ url }) => url === "/api/admin/mcp/servers/create")
    ).toBe(true)
  );
  expect(
    screen.getByRole("button", { name: messages.actions.mcpSetup.back })
  ).toBeDisabled();
  expect(
    screen.queryByRole("textbox", { name: "Server Name" })
  ).not.toBeInTheDocument();
  await user.keyboard("{Escape}");
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  await act(async () =>
    pending.resolve(new Response(JSON.stringify({ server_id: 7 })))
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  );
});

test("retries details loading after creation without creating a duplicate server", async () => {
  serverDetailsResponse = async () =>
    new Response("Unavailable", { status: 503 });
  const { user } = await openServerModal();
  await user.type(
    await screen.findByRole("textbox", { name: "Server Name" }),
    "Example MCP"
  );
  await user.type(
    screen.getByRole("textbox", { name: /^MCP Server URL/ }),
    configuredServer.server_url
  );
  await user.click(
    screen.getByRole("button", { name: messages.actions.mcpSetup.continue })
  );
  await waitFor(() => expect(savedRequests).toHaveLength(1));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: messages.actions.mcpSetup.continue })
    ).toBeEnabled()
  );
  expect(screen.getByRole("textbox", { name: "Server Name" })).toHaveValue(
    "Example MCP"
  );
  serverDetailsResponse = undefined;
  await user.click(
    screen.getByRole("button", { name: messages.actions.mcpSetup.continue })
  );
  expect(await screen.findByRole("tab", { name: "OAuth" })).toBeVisible();
  expect(savedRequests.filter(({ method }) => method === "POST")).toHaveLength(
    1
  );
});

describe("availability belongs to the detail page", () => {
  test.each([true, false])(
    "defaults Craft availability from the deployment during creation: %s",
    async (craftAvailable) => {
      settingsResponse = async () =>
        new Response(
          JSON.stringify({
            tier: Tier.BUSINESS,
            ee_features_enabled: true,
            onyx_craft_available: craftAvailable,
          })
        );
      const { user } = await openServerModal();
      await user.type(
        await screen.findByRole("textbox", { name: "Server Name" }),
        "MCP"
      );
      await user.type(
        screen.getByRole("textbox", { name: /^MCP Server URL/ }),
        configuredServer.server_url
      );
      expect(
        screen.queryByRole("switch", { name: /Available in/ })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Save Changes" })
      ).not.toBeInTheDocument();
      await user.click(
        screen.getByRole("button", { name: messages.actions.mcpSetup.continue })
      );
      await waitFor(() =>
        expect(savedRequests).toContainEqual({
          url: "/api/admin/mcp/server",
          method: "POST",
          payload: expect.objectContaining({
            available_in_craft: craftAvailable,
          }),
        })
      );
      expect(savedRequests[0]?.payload).not.toHaveProperty(
        "available_in_default_chat"
      );
      expect(await screen.findByRole("tab", { name: "OAuth" })).toBeVisible();
    }
  );

  test.each([true, false])(
    "editing server details does not overwrite saved availability: %s",
    async (available) => {
      const { user } = await openServerModal({
        ...configuredServer,
        available_in_craft: available,
      });
      await user.type(
        await screen.findByRole("textbox", { name: "Server Name" }),
        " updated"
      );
      expect(
        screen.queryByRole("switch", { name: /Available in/ })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", {
          name: messages.actions.mcpSetup.continue,
        })
      ).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Save Changes" }));
      await waitFor(() => expect(savedRequests).toHaveLength(1));
      expect(savedRequests[0]?.payload).not.toHaveProperty(
        "available_in_craft"
      );
      expect(savedRequests[0]?.payload).not.toHaveProperty(
        "available_in_default_chat"
      );
      await waitFor(() =>
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
      );
    }
  );
});

describe("inline server configuration", () => {
  function renderDetailsPage(
    options: {
      readOnly?: boolean;
      permissions?: Permission[];
      adminCapabilities?: Permission[];
      onBeforeUrlChange?: () => Promise<boolean>;
    } = {}
  ) {
    const {
      permissions = [Permission.MANAGE_ACTIONS],
      adminCapabilities = [],
      ...pageOptions
    } = options;
    const context = renderHook(() => UserProvider.useUser());
    const base = context.result.current;
    context.unmount();
    jest
      .mocked(UserProvider.useUser)
      .mockReturnValue({ ...base, permissions, adminCapabilities });
    const saved = jest.fn().mockResolvedValue(undefined);
    const dirty = jest.fn();
    render(
      <MCPServerDetailsPage
        active
        variant="page"
        server={configuredServer}
        onSaved={saved}
        onBusyChange={() => {}}
        onDirtyChange={dirty}
        afterFields={<span>Availability controls</span>}
        {...pageOptions}
      />
    );
    return { saved, dirty };
  }

  test("saves inline without a modal, cancel button, or step navigation", async () => {
    const { saved, dirty } = renderDetailsPage();
    const user = setupUser();
    await user.type(
      await screen.findByRole("textbox", { name: "Server Name" }),
      " updated"
    );
    expect(screen.getByText("Availability controls")).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Cancel" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: messages.actions.mcpSetup.continue })
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() =>
      expect(saved).toHaveBeenCalledWith(
        expect.objectContaining({ id: 7 }),
        false
      )
    );
    expect(screen.getByRole("textbox", { name: "Server Name" })).toHaveValue(
      "Example MCP updated"
    );
    await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(false));
  });

  test("keeps URL edits when replacing another tab's draft is canceled", async () => {
    const beforeChange = jest.fn().mockResolvedValue(false);
    const { saved } = renderDetailsPage({ onBeforeUrlChange: beforeChange });
    const user = setupUser();
    const url = await screen.findByRole("textbox", { name: /^MCP Server URL/ });
    await user.clear(url);
    await user.type(url, "https://new.example.com/mcp");
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() => expect(beforeChange).toHaveBeenCalledTimes(1));
    expect(savedRequests).toHaveLength(0);
    expect(saved).not.toHaveBeenCalled();
    expect(url).toHaveValue("https://new.example.com/mcp");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save Changes" })).toBeEnabled()
    );
    beforeChange.mockResolvedValue(true);
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() => expect(savedRequests).toHaveLength(1));
  });

  test.each([
    { adminCapabilities: [] },
    { adminCapabilities: [Permission.MANAGE_ACTIONS] },
  ])(
    "read-only configuration loads without global edit permission and preserves Public access: %j",
    async ({ adminCapabilities }) => {
      renderDetailsPage({ readOnly: true, permissions: [], adminCapabilities });
      expect(
        await screen.findByRole("textbox", { name: "Server Name" })
      ).toBeDisabled();
      expect(
        screen.getByRole("textbox", { name: /^MCP Server URL/ })
      ).toBeDisabled();
      expect(
        screen.queryByRole("button", { name: "Save Changes" })
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole("combobox", { name: "Access control" })
      ).toHaveValue("Public");
      expect(
        screen.getByRole("combobox", { name: "Access control" })
      ).toBeDisabled();
      expect(
        screen.getByRole("textbox", { name: "Server Name" })
      ).not.toHaveFocus();
    }
  );
});
