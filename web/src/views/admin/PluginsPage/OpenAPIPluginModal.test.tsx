import {
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { toast } from "@opal/layouts";
import type { ToolSnapshot } from "@/lib/tools/types";
import type { RawToolSnapshot } from "@/lib/tools/enrich";
import messages from "@/i18n/messages/en.json";
import OpenAPIPluginModal from "@/views/admin/PluginsPage/OpenAPIPluginModal";

const copy = messages.actions;
const authCopy = copy.openApiAuthModal;

const mockReplace = jest.fn();
const mockPush = jest.fn();
const mockRouter = { push: mockPush, replace: mockReplace };
jest.mock("next/navigation", () => ({
  ...jest.requireActual("next/navigation"),
  useRouter: () => mockRouter,
  useSearchParams: () => new URLSearchParams(),
}));

let mockFullAdmin = false;
jest.mock("@/lib/permissions/hooks", () => ({
  ...jest.requireActual("@/lib/permissions/hooks"),
  usePermissionAuthority: () => ({
    isGlobalHolder: mockFullAdmin,
    isScopedManager: false,
  }),
}));

const definition = {
  openapi: "3.0.0",
  info: {
    title: "Release API",
    description: "Read release status",
    version: "1.0",
  },
  servers: [{ url: "https://releases.example.com" }],
  paths: {
    "/releases": {
      get: {
        operationId: "listReleases",
        summary: "List releases",
        responses: { "200": { description: "Releases" } },
      },
    },
  },
};
const schemaText = JSON.stringify(definition);

// The raw API shape: an empty name or description is no override, and the
// modal shows the schema's "Release API" and "Read release status".
const savedTool: RawToolSnapshot = {
  id: 42,
  name: "",
  display_name: "",
  description: "",
  definition,
  custom_headers: [],
  passthrough_auth: false,
  oauth_config_id: 7,
  in_code_tool_id: null,
  enabled: true,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: false,
  permissions: { edit: true, delete: true, toggle: true, authenticate: true },
};

interface Write {
  path: string;
  method: string;
  body: unknown;
}

// A small fake of the server the modal talks to.
let tools: RawToolSnapshot[];
let writes: Write[];
let configs: Set<number>;
let toolCreates: number;
let configCreates: number;
let validateError: string | null;
let failCreate: string | null;
let failNextLink: boolean;
let createdPermissions: RawToolSnapshot["permissions"];

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });

function updateTool(id: number, update: Partial<RawToolSnapshot>) {
  tools = tools.map((tool) => (tool.id === id ? { ...tool, ...update } : tool));
}

beforeEach(() => {
  toast.clearAll();
  mockReplace.mockClear();
  mockPush.mockClear();
  mockFullAdmin = false;
  tools = [{ ...savedTool }];
  writes = [];
  configs = new Set([7]);
  toolCreates = 0;
  configCreates = 0;
  validateError = null;
  failCreate = null;
  failNextLink = false;
  createdPermissions = { edit: true, toggle: true, authenticate: true };
  jest.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    const method = init?.method ?? "GET";
    if (path === "/api/tool/openapi") return json(tools);
    if (path === "/api/settings" || path === "/api/enterprise-settings")
      return json({});
    if (path === "/api/auth/type") return json({ oauth_enabled: true });
    if (path === "/api/admin/oauth-config/pkce-support")
      return json({ status: "unknown" });
    if (path === "/api/admin/tool/custom/validate")
      return validateError
        ? json({ detail: validateError }, 400)
        : json({
            methods: [
              {
                name: "listReleases",
                summary: "List releases",
                method: "GET",
                path: "/releases",
              },
            ],
          });
    if (path === "/api/admin/default-assistant/configuration")
      return json({ tool_ids: [5] });
    if (path.startsWith("/api/admin/oauth-config/") && method === "GET") {
      const id = Number(path.split("/").at(-1));
      return json({
        id,
        name: "Release OAuth",
        authorization_url: "https://identity.example.com/authorize",
        token_url: "https://identity.example.com/token",
        scopes: ["read"],
        has_client_credentials: true,
      });
    }
    if (method === "GET") throw new Error(`Unexpected request ${path}`);

    const body: unknown = init?.body ? JSON.parse(String(init.body)) : null;
    writes.push({ path, method, body });
    if (path === "/api/admin/tool/custom") {
      if (failCreate) return json({ detail: failCreate }, 400);
      toolCreates += 1;
      const created: RawToolSnapshot = {
        ...savedTool,
        id: 43,
        oauth_config_id: null,
        permissions: createdPermissions,
      };
      tools = [...tools, created];
      return json(created);
    }
    if (path === "/api/admin/oauth-config/create") {
      configCreates += 1;
      const id = 98 + configCreates;
      configs.add(id);
      return json({ id });
    }
    if (path.startsWith("/api/admin/oauth-config/")) return json({ id: 7 });
    if (path === "/api/admin/tool/status")
      return json({ updated_count: 1, tool_ids: [] });
    if (path === "/api/admin/default-assistant") return json(body);
    const toolMatch = path.match(/^\/api\/admin\/tool\/custom\/(\d+)$/);
    if (toolMatch) {
      const update = body as Partial<RawToolSnapshot>;
      if (update.oauth_config_id && failNextLink) {
        failNextLink = false;
        return json({ detail: "Link failed" }, 503);
      }
      const id = Number(toolMatch[1]);
      updateTool(id, update);
      return json(tools.find((tool) => tool.id === id));
    }
    throw new Error(`Unexpected request ${method} ${path}`);
  });
});

afterEach(() => {
  toast.clearAll();
  jest.restoreAllMocks();
});

function writesTo(path: string) {
  return writes.filter((write) => write.path === path);
}

function tab(name: string) {
  return screen.getByRole("tab", { name });
}

function primaryButton(name: string) {
  return screen.getByRole("button", { name });
}

function schemaField() {
  return screen.getByPlaceholderText(
    copy.addOpenApiModal.definition.placeholder
  );
}

async function selectAuthMethod(label: string) {
  const user = setupUser();
  await user.click(
    screen.getByRole("combobox", { name: authCopy.authMethod.placeholder })
  );
  // Option names include their descriptions, so match the title text.
  const listbox = await screen.findByRole("listbox");
  const option = within(listbox)
    .getByText(label, { exact: true })
    .closest('[role="option"]');
  if (!option) throw new Error(`No option ${label}`);
  fireEvent.click(option);
}

function fillOAuth(fields: {
  authorizationUrl: string;
  tokenUrl: string;
  clientId: string;
  clientSecret: string;
}) {
  fireEvent.change(
    screen.getByRole("textbox", { name: authCopy.authorizationUrl.label }),
    { target: { value: fields.authorizationUrl } }
  );
  fireEvent.change(
    screen.getByRole("textbox", { name: authCopy.tokenUrl.label }),
    { target: { value: fields.tokenUrl } }
  );
  fireEvent.change(
    screen.getByRole("textbox", { name: authCopy.clientId.label }),
    { target: { value: fields.clientId } }
  );
  fireEvent.change(screen.getByLabelText(authCopy.clientSecret.label), {
    target: { value: fields.clientSecret },
  });
}

const workspaceSwitchName = new RegExp(
  `^${copy.plugins.openapi.workspaceEnabled.title}`
);

const validOAuth = {
  authorizationUrl: "https://identity.example.com/authorize",
  tokenUrl: "https://identity.example.com/token",
  clientId: "release-client",
  clientSecret: "release-secret",
};

describe("add", () => {
  const addLabel = copy.addOpenApiModal.submitButton.addLabel;
  const continueLabel = copy.mcpSetup.continue;

  function renderAdd() {
    const onClose = jest.fn();
    const onCreated = jest.fn();
    const view = render(
      <OpenAPIPluginModal onClose={onClose} onCreated={onCreated} />
    );
    return { ...view, onClose, onCreated };
  }

  async function continueWithSchema(text = schemaText) {
    fireEvent.change(schemaField(), { target: { value: text } });
    await setupUser().click(primaryButton(continueLabel));
    await waitFor(() =>
      expect(tab(copy.mcpDetail.authentication)).toHaveAttribute(
        "aria-selected",
        "true"
      )
    );
  }

  test("opens on the schema tab and locks the other tabs until the schema passes", async () => {
    renderAdd();
    expect(
      await screen.findByRole("dialog", {
        name: new RegExp(`^${copy.addOpenApiModal.addHeader.title}`),
      })
    ).toHaveAccessibleDescription(copy.addOpenApiModal.addHeader.description);
    expect(tab(copy.plugins.openapi.tabs.schema)).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(tab(copy.plugins.openapi.tabs.details)).toBeDisabled();
    expect(tab(copy.mcpDetail.authentication)).toBeDisabled();
    expect(primaryButton(continueLabel)).toBeDisabled();

    fireEvent.change(schemaField(), { target: { value: schemaText } });
    // The debounced check previews the schema and unlocks the tabs.
    expect(await screen.findByText("listReleases")).toBeVisible();
    expect(screen.getByText("https://releases.example.com")).toBeVisible();
    expect(tab(copy.plugins.openapi.tabs.details)).toBeEnabled();
    expect(tab(copy.mcpDetail.authentication)).toBeEnabled();
    expect(primaryButton(continueLabel)).toBeEnabled();
  });

  test.each([
    [
      "invalid JSON",
      "{invalid",
      null,
      copy.addOpenApiModal.definition.invalidJson,
    ],
    [
      "a server rejection",
      schemaText,
      "Schema has no paths",
      "Schema has no paths",
    ],
  ])(
    "shows %s as the schema error and does not continue",
    async (_case, text, serverError, message) => {
      validateError = serverError;
      renderAdd();
      fireEvent.change(schemaField(), { target: { value: text } });
      await setupUser().click(primaryButton(continueLabel));
      expect(await screen.findByText(message)).toBeVisible();
      expect(tab(copy.plugins.openapi.tabs.schema)).toHaveAttribute(
        "aria-selected",
        "true"
      );
      expect(tab(copy.mcpDetail.authentication)).toBeDisabled();
      expect(writes).toEqual([]);
    }
  );

  test("accepts trailing commas and Python literals in the schema", async () => {
    renderAdd();
    const lenient = JSON.stringify({ ...definition, "x-flag": true })
      .replace('"x-flag":true', '"x-flag":True')
      .replace(/}$/, ",}");
    await continueWithSchema(lenient);
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/admin/tool/custom/validate",
      expect.objectContaining({
        body: JSON.stringify({
          definition: { ...definition, "x-flag": true },
        }),
      })
    );
  });

  test("creates a plugin without authentication and reports its id", async () => {
    const user = setupUser();
    const { onCreated, onClose } = renderAdd();
    await continueWithSchema();
    expect(screen.getByText(authCopy.noAuthNotice.title)).toBeVisible();
    await user.click(tab(copy.plugins.openapi.tabs.details));
    expect(
      screen.getByRole("textbox", { name: /Display Name/ })
    ).toHaveAttribute("placeholder", "Release API");
    fireEvent.change(screen.getByRole("textbox", { name: /Display Name/ }), {
      target: { value: "Releases" },
    });
    await waitFor(() => expect(primaryButton(addLabel)).toBeEnabled());
    await user.click(primaryButton(addLabel));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(43));
    expect(writesTo("/api/admin/tool/custom")).toEqual([
      {
        path: "/api/admin/tool/custom",
        method: "POST",
        body: {
          name: "Releases",
          description: "",
          definition,
          custom_headers: [],
          passthrough_auth: false,
        },
      },
    ]);
    // No authentication and the workspace switch on need no further writes.
    expect(writes).toHaveLength(1);
    expect(onClose).not.toHaveBeenCalled();
  });

  test("turns a new plugin off when the workspace switch is off", async () => {
    const user = setupUser();
    const { onCreated } = renderAdd();
    await continueWithSchema();
    await user.click(tab(copy.plugins.openapi.tabs.details));
    await user.click(
      screen.getByRole("switch", {
        name: workspaceSwitchName,
      })
    );
    await user.click(primaryButton(addLabel));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(43));
    expect(writesTo("/api/admin/tool/status")).toEqual([
      {
        path: "/api/admin/tool/status",
        method: "PATCH",
        body: { tool_ids: [43], enabled: false },
      },
    ]);
  });

  test("adds a full admin's new plugin to the default Chat", async () => {
    mockFullAdmin = true;
    const user = setupUser();
    const { onCreated } = renderAdd();
    await continueWithSchema();
    await waitFor(() => expect(primaryButton(addLabel)).toBeEnabled());
    await user.click(primaryButton(addLabel));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(43));
    expect(writesTo("/api/admin/default-assistant")).toEqual([
      {
        path: "/api/admin/default-assistant",
        method: "PATCH",
        body: { tool_ids: [5, 43] },
      },
    ]);
    expect(writesTo("/api/admin/tool/status")).toEqual([]);
  });

  test("shows a create failure in the modal and as a toast", async () => {
    failCreate = "Schema name already exists";
    const showError = jest.spyOn(toast, "error");
    const user = setupUser();
    const { onCreated, onClose } = renderAdd();
    await continueWithSchema();
    await user.click(primaryButton(addLabel));
    const message = "Failed to create tool: Schema name already exists";
    expect(await screen.findByText(message)).toBeVisible();
    expect(showError).toHaveBeenCalledWith(message);
    expect(onCreated).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(primaryButton(addLabel)).toBeEnabled();
  });

  test("gates Add on valid OAuth fields and rejects masked credentials", async () => {
    renderAdd();
    await continueWithSchema();
    await selectAuthMethod(authCopy.authMethod.oauth.label);
    await waitFor(() => expect(primaryButton(addLabel)).toBeDisabled());
    fillOAuth({ ...validOAuth, authorizationUrl: "not-a-url" });
    await waitFor(() => expect(primaryButton(addLabel)).toBeDisabled());
    fillOAuth({ ...validOAuth, clientSecret: "********" });
    await waitFor(() => expect(primaryButton(addLabel)).toBeDisabled());
    fillOAuth(validOAuth);
    await waitFor(() => expect(primaryButton(addLabel)).toBeEnabled());

    // A hidden invalid OAuth draft does not block another method, and stays.
    fillOAuth({ ...validOAuth, authorizationUrl: "not-a-url" });
    await selectAuthMethod(authCopy.authMethod.ptOauth.label);
    expect(screen.getByText(authCopy.passThroughNotice.title)).toBeVisible();
    await waitFor(() => expect(primaryButton(addLabel)).toBeEnabled());
    await selectAuthMethod(authCopy.authMethod.oauth.label);
    expect(
      screen.getByRole("textbox", { name: authCopy.authorizationUrl.label })
    ).toHaveValue("not-a-url");
    await waitFor(() => expect(primaryButton(addLabel)).toBeDisabled());
  });

  test("requires a value for a custom header", async () => {
    const user = setupUser();
    const { onCreated } = renderAdd();
    await continueWithSchema();
    await selectAuthMethod(authCopy.authMethod.customHeader.label);
    await waitFor(() => expect(primaryButton(addLabel)).toBeDisabled());
    fireEvent.change(screen.getByRole("textbox", { name: "Value 1" }), {
      target: { value: "release-key" },
    });
    await waitFor(() => expect(primaryButton(addLabel)).toBeEnabled());
    await user.click(primaryButton(addLabel));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(43));
    expect(writesTo("/api/admin/tool/custom/43")).toEqual([
      {
        path: "/api/admin/tool/custom/43",
        method: "PUT",
        body: {
          custom_headers: [{ key: "Authorization", value: "release-key" }],
          passthrough_auth: false,
          oauth_config_id: null,
        },
      },
    ]);
  });

  test("retries a failed OAuth link with the same tool and configuration", async () => {
    failNextLink = true;
    const user = setupUser();
    const { onCreated } = renderAdd();
    await continueWithSchema();
    await selectAuthMethod(authCopy.authMethod.oauth.label);
    fillOAuth(validOAuth);
    await waitFor(() => expect(primaryButton(addLabel)).toBeEnabled());
    await user.click(primaryButton(addLabel));
    expect(await screen.findByText(/Link failed/)).toBeVisible();
    expect(onCreated).not.toHaveBeenCalled();

    await user.click(primaryButton(addLabel));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(43));
    expect(toolCreates).toBe(1);
    expect(configCreates).toBe(1);
    expect(writesTo("/api/admin/oauth-config/create")[0]?.body).toEqual(
      expect.objectContaining({
        client_id: "release-client",
        client_secret: "release-secret",
      })
    );
    expect(tools.find((tool) => tool.id === 43)?.oauth_config_id).toBe(99);
  });

  test("Cancel closes without writing", async () => {
    const { onClose } = renderAdd();
    fireEvent.change(schemaField(), { target: { value: schemaText } });
    await setupUser().click(
      screen.getByRole("button", {
        name: copy.addOpenApiModal.cancelButton.label,
      })
    );
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(writes).toEqual([]);
  });
});

describe("edit", () => {
  const updateLabel = copy.addOpenApiModal.submitButton.saveLabel;

  const onEditClose = jest.fn();
  beforeEach(() => onEditClose.mockClear());

  async function renderEdit(
    params?: URLSearchParams,
    name: RegExp = /^Edit Release API/
  ) {
    render(
      <OpenAPIPluginModal toolId={42} params={params} onClose={onEditClose} />
    );
    return screen.findByRole("dialog", { name });
  }

  async function openDetails() {
    await setupUser().click(tab(copy.plugins.openapi.tabs.details));
  }

  async function openAuthentication() {
    await setupUser().click(tab(copy.mcpDetail.authentication));
    await waitFor(() =>
      expect(
        screen.getByRole("textbox", { name: authCopy.tokenUrl.label })
      ).toHaveValue("https://identity.example.com/token")
    );
  }

  test("opens on the schema, with the stored overrides in Plugin Details", async () => {
    tools = [{ ...savedTool, name: "Releases", display_name: "Releases" }];
    await renderEdit(undefined, /^Edit Releases/);
    expect(screen.getByRole("dialog")).toHaveAccessibleDescription(
      copy.addOpenApiModal.editHeader.description
    );
    expect(tab(copy.plugins.openapi.tabs.schema)).toHaveAttribute(
      "aria-selected",
      "true"
    );
    await openDetails();
    expect(screen.getByRole("textbox", { name: /Display Name/ })).toHaveValue(
      "Releases"
    );
    const description = screen.getByRole("textbox", { name: /^Description/ });
    expect(description).toHaveValue("");
    expect(description).toHaveAttribute("placeholder", "Read release status");
    expect(
      screen.getByRole("switch", {
        name: workspaceSwitchName,
      })
    ).toBeChecked();
    expect(primaryButton(updateLabel)).toBeDisabled();
  });

  test("saves only the changed name and closes", async () => {
    const user = setupUser();
    await renderEdit();
    await openDetails();
    fireEvent.change(screen.getByRole("textbox", { name: /Display Name/ }), {
      target: { value: "Deployments" },
    });
    await waitFor(() => expect(primaryButton(updateLabel)).toBeEnabled());
    await user.click(primaryButton(updateLabel));
    await waitFor(() => expect(onEditClose).toHaveBeenCalled());
    expect(mockReplace).not.toHaveBeenCalled();
    expect(mockPush).not.toHaveBeenCalled();
    expect(writes).toEqual([
      {
        path: "/api/admin/tool/custom/42",
        method: "PUT",
        body: { oauth_config_id: 7, name: "Deployments", description: "" },
      },
    ]);
  });

  test("saves only the workspace switch", async () => {
    const user = setupUser();
    await renderEdit();
    await openDetails();
    await user.click(
      screen.getByRole("switch", {
        name: workspaceSwitchName,
      })
    );
    await user.click(primaryButton(updateLabel));
    await waitFor(() => expect(onEditClose).toHaveBeenCalled());
    expect(writes).toEqual([
      {
        path: "/api/admin/tool/status",
        method: "PATCH",
        body: { tool_ids: [42], enabled: false },
      },
    ]);
  });

  test("checks and saves a changed schema", async () => {
    const user = setupUser();
    await renderEdit();
    await user.click(tab(copy.plugins.openapi.tabs.schema));
    const updated = {
      ...definition,
      info: { ...definition.info, description: "Updated release status" },
    };
    fireEvent.change(schemaField(), {
      target: { value: JSON.stringify(updated) },
    });
    await waitFor(() => expect(primaryButton(updateLabel)).toBeEnabled());
    await user.click(primaryButton(updateLabel));
    await waitFor(() => expect(onEditClose).toHaveBeenCalled());
    expect(writes).toEqual([
      {
        path: "/api/admin/tool/custom/42",
        method: "PUT",
        body: {
          oauth_config_id: 7,
          name: "",
          description: "",
          definition: updated,
        },
      },
    ]);
  });

  test("keeps masked OAuth credentials when saving other OAuth fields", async () => {
    const user = setupUser();
    await renderEdit();
    await openAuthentication();
    expect(
      screen.getByRole("textbox", { name: authCopy.clientId.label })
    ).toHaveValue("********");
    fireEvent.change(
      screen.getByRole("textbox", { name: authCopy.tokenUrl.label }),
      { target: { value: "https://identity.example.com/new-token" } }
    );
    await waitFor(() => expect(primaryButton(updateLabel)).toBeEnabled());
    await user.click(primaryButton(updateLabel));
    await waitFor(() => expect(onEditClose).toHaveBeenCalled());
    expect(writes).toEqual([
      {
        path: "/api/admin/oauth-config/7",
        method: "PUT",
        body: {
          authorization_url: "https://identity.example.com/authorize",
          token_url: "https://identity.example.com/new-token",
          scopes: ["read"],
          supports_pkce: false,
        },
      },
      {
        path: "/api/admin/tool/custom/42",
        method: "PUT",
        body: {
          custom_headers: [],
          passthrough_auth: false,
          oauth_config_id: 7,
        },
      },
    ]);
  });

  test("clears saved OAuth with None", async () => {
    const user = setupUser();
    await renderEdit();
    await openAuthentication();
    await selectAuthMethod(authCopy.authMethod.none.label);
    await waitFor(() => expect(primaryButton(updateLabel)).toBeEnabled());
    await user.click(primaryButton(updateLabel));
    await waitFor(() => expect(onEditClose).toHaveBeenCalled());
    expect(writes).toEqual([
      {
        path: "/api/admin/tool/custom/42",
        method: "PUT",
        body: {
          custom_headers: [],
          passthrough_auth: false,
          oauth_config_id: null,
        },
      },
    ]);
  });

  test("shows a save failure in the modal and stays open", async () => {
    failNextLink = true;
    const showError = jest.spyOn(toast, "error");
    const user = setupUser();
    await renderEdit();
    await openAuthentication();
    fireEvent.change(
      screen.getByRole("textbox", { name: authCopy.tokenUrl.label }),
      { target: { value: "https://identity.example.com/new-token" } }
    );
    await waitFor(() => expect(primaryButton(updateLabel)).toBeEnabled());
    await user.click(primaryButton(updateLabel));
    const message = "Failed to update tool: Link failed";
    expect(await screen.findByText(message)).toBeVisible();
    expect(showError).toHaveBeenCalledWith(message);
    expect(onEditClose).not.toHaveBeenCalled();
    expect(primaryButton(updateLabel)).toBeEnabled();
  });

  test("does not write when the fresh tool no longer permits editing", async () => {
    const user = setupUser();
    await renderEdit();
    await openDetails();
    fireEvent.change(screen.getByRole("textbox", { name: /Display Name/ }), {
      target: { value: "Deployments" },
    });
    tools = [{ ...savedTool, permissions: { authenticate: true } }];
    await waitFor(() => expect(primaryButton(updateLabel)).toBeEnabled());
    await user.click(primaryButton(updateLabel));
    expect(
      await screen.findByText(copy.addOpenApiModal.toasts.updateFailed)
    ).toBeVisible();
    expect(writes).toEqual([]);
    expect(onEditClose).not.toHaveBeenCalled();
  });

  test("opens Authentication once from the configure parameter without URL writes", async () => {
    await renderEdit(
      new URLSearchParams("configure=authentication&source=create")
    );
    await waitFor(() =>
      expect(tab(copy.mcpDetail.authentication)).toHaveAttribute(
        "aria-selected",
        "true"
      )
    );
    await setupUser().click(tab(copy.plugins.openapi.tabs.schema));
    await waitFor(() =>
      expect(tab(copy.plugins.openapi.tabs.schema)).toHaveAttribute(
        "aria-selected",
        "true"
      )
    );
    expect(tab(copy.mcpDetail.authentication)).toHaveAttribute(
      "aria-selected",
      "false"
    );
    expect(mockReplace).not.toHaveBeenCalled();
    expect(mockPush).not.toHaveBeenCalled();
  });

  test("closes through onClose without routing", async () => {
    await renderEdit();
    await setupUser().click(screen.getByRole("button", { name: "Close" }));
    expect(onEditClose).toHaveBeenCalled();
    expect(mockReplace).not.toHaveBeenCalled();
    expect(mockPush).not.toHaveBeenCalled();
  });

  test("shows read-only views without edit permissions", async () => {
    tools = [
      {
        ...savedTool,
        description: "",
        oauth_config_id: null,
        permissions: {},
      },
    ];
    const user = setupUser();
    await renderEdit();
    await openDetails();
    // An empty stored description falls back to the schema's.
    expect(screen.getByText("Read release status")).toBeVisible();
    expect(
      screen.queryByRole("textbox", { name: /Display Name/ })
    ).not.toBeInTheDocument();
    await user.click(tab(copy.plugins.openapi.tabs.schema));
    expect(
      screen.getByRole("textbox", { name: copy.plugins.openapi.tabs.schema })
    ).toBeDisabled();
    expect(screen.getByText("listReleases")).toBeVisible();
    await user.click(tab(copy.mcpDetail.authentication));
    expect(screen.getByText(authCopy.authMethod.none.label)).toBeVisible();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: updateLabel })
    ).not.toBeInTheDocument();
  });

  test("hides only the controls a partial permission does not grant", async () => {
    tools = [
      { ...savedTool, permissions: { edit: true, authenticate: false } },
    ];
    const user = setupUser();
    await renderEdit();
    await openDetails();
    expect(
      screen.getByRole("textbox", { name: /Display Name/ })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("switch", {
        name: workspaceSwitchName,
      })
    ).not.toBeInTheDocument();
    await user.click(tab(copy.mcpDetail.authentication));
    expect(screen.getByText(authCopy.authMethod.oauth.label)).toBeVisible();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(primaryButton(updateLabel)).toBeDisabled();
  });
});
