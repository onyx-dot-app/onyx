jest.mock("next/navigation", () => ({
  ...jest.requireActual("next/navigation"),
  useRouter: () => ({ push: jest.fn() }),
}));

import { Form, Formik } from "formik";
import { Button } from "@opal/components";
import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import MCPServerDetailsPage, {
  MCPAccessControl,
  validateMCPAccess,
} from "@/views/admin/PluginsPage/components/mcp/MCPServerDetailsPage";
import { renderHook } from "@testing-library/react";
import * as UserProvider from "@/providers/UserProvider";
import { Permission } from "@/lib/types";
import {
  MCPServerStatus,
  type MCPServer,
  type MCPServerConfigurationValues,
} from "@/lib/mcp/types";
import messages from "@/i18n/messages/en.json";
import { Tier } from "@/lib/tiers/types";
import { useSWRConfig } from "swr";

jest.mock("@/providers/UserProvider", () => {
  const actual = jest.requireActual<typeof UserProvider>(
    "@/providers/UserProvider"
  );
  return { ...actual, useUser: jest.fn(actual.useUser) };
});

const initialValues: MCPServerConfigurationValues = {
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
  values?: MCPServerConfigurationValues;
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
let savedRequests: {
  url: string;
  method: string | undefined;
  payload: unknown;
}[];

let serverRecord: MCPServer;

let availableGroups: { id: number; name: string; users: never[] }[];
let workspaceTier: Tier;

function RefreshSettings() {
  const { mutate } = useSWRConfig();
  return (
    <Button onClick={() => void mutate("/api/settings")}>
      Refresh settings
    </Button>
  );
}

beforeEach(() => {
  jest
    .mocked(UserProvider.useUser)
    .mockImplementation(
      jest.requireActual<typeof UserProvider>("@/providers/UserProvider")
        .useUser
    );
  savedRequests = [];
  workspaceTier = Tier.BUSINESS;
  serverRecord = configuredServer;
  saveResponse = async () => new Response(JSON.stringify(serverRecord));
  availableGroups = [
    { id: 1, name: "Engineering", users: [] },
    { id: 2, name: "Support", users: [] },
  ];
  jest.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
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
    if (url === "/api/settings")
      return new Response(
        JSON.stringify({ tier: workspaceTier, ee_features_enabled: true })
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
  connection_status: null,
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

describe("inline server configuration", () => {
  function renderDetailsPage(
    options: {
      readOnly?: boolean;
      permissions?: Permission[];
      adminCapabilities?: Permission[];
      server?: MCPServer;
    } = {}
  ) {
    const {
      permissions = [Permission.MANAGE_ACTIONS],
      adminCapabilities = [],
      server = configuredServer,
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
      <>
        <MCPServerDetailsPage
          active
          variant="page"
          server={server}
          onSaved={saved}
          onBusyChange={() => {}}
          onDirtyChange={dirty}
          {...pageOptions}
        />
        <RefreshSettings />
      </>
    );
    return { saved, dirty };
  }

  test("metadata edits preserve restricted grants without creating another server", async () => {
    const restricted = {
      ...configuredServer,
      is_public: false,
      groups: [1],
      users: ["existing-user"],
    };
    serverRecord = restricted;
    const { saved } = renderDetailsPage({ server: restricted });
    const user = setupUser();
    const name = await screen.findByRole("textbox", { name: "Server Name" });
    await user.clear(name);
    await user.type(name, "Updated MCP");
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() =>
      expect(saved).toHaveBeenCalledWith(
        expect.objectContaining({ id: 7, name: "Updated MCP" })
      )
    );
    expect(savedRequests).toEqual([
      {
        url: "/api/admin/mcp/server/7",
        method: "PATCH",
        payload: {
          name: "Updated MCP",
          description: "Tools for support",
          server_url: "https://example.com/mcp",
        },
      },
    ]);
  });

  test.each([{ groups: [1] }, { groups: [] }])(
    "allows metadata-only saves on Free with unchanged restricted grants %j",
    async ({ groups }) => {
      workspaceTier = Tier.COMMUNITY;
      const restricted = {
        ...configuredServer,
        is_public: false,
        groups,
        users: [],
      };
      serverRecord = restricted;
      const { saved } = renderDetailsPage({ server: restricted });
      const user = setupUser();
      await user.type(
        await screen.findByRole("textbox", { name: "Server Name" }),
        " renamed"
      );
      await waitFor(() =>
        expect(
          screen.getByRole("button", { name: "Save Changes" })
        ).toBeEnabled()
      );
      await user.click(screen.getByRole("button", { name: "Save Changes" }));
      await waitFor(() => expect(saved).toHaveBeenCalled());
      expect(savedRequests).toEqual([
        {
          url: "/api/admin/mcp/server/7",
          method: "PATCH",
          payload: {
            name: "Example MCP renamed",
            description: "Tools for support",
            server_url: configuredServer.server_url,
          },
        },
      ]);
      expect(saved).toHaveBeenCalledWith(
        expect.objectContaining({ is_public: false, groups, users: [] })
      );
    }
  );

  test("does not save a changed restricted grant after the workspace loses Business access", async () => {
    const restricted = {
      ...configuredServer,
      is_public: false,
      groups: [1],
      users: [],
    };
    renderDetailsPage({ server: restricted });
    const user = setupUser();
    await screen.findByRole("textbox", { name: "Server Name" });
    const picker = screen.getByPlaceholderText("Add user groups");
    await waitFor(() => expect(picker).toBeEnabled());
    await user.type(picker, "Support");
    await user.click(await screen.findByRole("option", { name: /^Support/ }));
    workspaceTier = Tier.COMMUNITY;
    await user.click(screen.getByRole("button", { name: "Refresh settings" }));
    await user.click(screen.getByRole("combobox", { name: "Access control" }));
    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: /^User groups/ })
      ).toHaveAttribute("aria-disabled", "true")
    );
    await user.keyboard("{Escape}");
    await user.type(
      screen.getByRole("textbox", { name: "Server Name" }),
      " renamed"
    );
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    expect(savedRequests).toEqual([]);
  });

  test("failed metadata saves retain edits and permit retry", async () => {
    saveResponse = async () =>
      new Response("Provider is unavailable", { status: 503 });
    const { saved } = renderDetailsPage();
    const user = setupUser();
    const name = await screen.findByRole("textbox", { name: "Server Name" });
    await user.type(name, " updated");
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() => expect(savedRequests).toHaveLength(1));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save Changes" })).toBeEnabled()
    );
    expect(name).toHaveValue("Example MCP updated");
    expect(saved).not.toHaveBeenCalled();
    saveResponse = async () => new Response(JSON.stringify(serverRecord));
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() =>
      expect(saved).toHaveBeenCalledWith(
        expect.objectContaining({ id: 7, name: "Example MCP updated" })
      )
    );
    expect(savedRequests).toHaveLength(2);
  });

  test("saves inline without a modal, cancel button, or step navigation", async () => {
    const { saved, dirty } = renderDetailsPage();
    const user = setupUser();
    await user.type(
      await screen.findByRole("textbox", { name: "Server Name" }),
      " updated"
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Cancel" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: messages.actions.mcpSetup.continue })
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() =>
      expect(saved).toHaveBeenCalledWith(expect.objectContaining({ id: 7 }))
    );
    expect(screen.getByRole("textbox", { name: "Server Name" })).toHaveValue(
      "Example MCP updated"
    );
    await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(false));
  });

  test("keeps the saved endpoint fixed while metadata remains editable", async () => {
    const { saved } = renderDetailsPage();
    const user = setupUser();
    await user.type(
      await screen.findByRole("textbox", { name: "Server Name" }),
      " updated"
    );
    expect(
      screen.queryByRole("textbox", { name: /^MCP Server URL/ })
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() => expect(savedRequests).toHaveLength(1));
    expect(savedRequests[0]?.payload).toEqual(
      expect.objectContaining({ server_url: configuredServer.server_url })
    );
    expect(saved).toHaveBeenCalledWith(
      expect.objectContaining({ server_url: configuredServer.server_url })
    );
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
        screen.queryByRole("textbox", { name: /^MCP Server URL/ })
      ).not.toBeInTheDocument();
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
