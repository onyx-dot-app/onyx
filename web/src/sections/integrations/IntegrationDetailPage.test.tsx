import { PointerEventsCheckLevel } from "@testing-library/user-event";
import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import IntegrationDetailPage from "@/sections/integrations/IntegrationDetailPage";
import messages from "@/i18n/messages/en.json";
import {
  makeDetail,
  mockFetch,
  requestBody,
} from "@tests/setup/integrationTestUtils";

const copy = messages.admin.integrations;
const detailCopy = copy.detail;

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => window.location.pathname,
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

const URL_DETAIL = "/api/admin/integrations/1";
const URL_ACTIONS = `${URL_DETAIL}/actions`;
const NO_ACTIONS = { default_policy: null, actions: [] };

function user() {
  return setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
}

function open(tab?: string) {
  window.history.replaceState(
    null,
    "",
    tab ? `/admin/integrations/1?tab=${tab}` : "/admin/integrations/1"
  );
  render(<IntegrationDetailPage integrationId={1} />);
}

function activePanel(): HTMLElement {
  const panel = document.querySelector<HTMLElement>(
    '[role="tabpanel"][data-state="active"]'
  );
  if (!panel) throw new Error("No active tab panel");
  return panel;
}

/** The tabs stay mounted, so query only the open one. */
async function inPanel() {
  await waitFor(() => activePanel());
  return within(activePanel());
}

afterEach(() => jest.restoreAllMocks());

// ── Page ─────────────────────────────────────────────────────────────────────

test("shows the three tabs and opens a tab in the URL", async () => {
  mockFetch({ [URL_DETAIL]: makeDetail() });
  const u = user();
  open();
  expect(
    await screen.findByRole("tab", { name: detailCopy.tabs.overview })
  ).toHaveAttribute("aria-selected", "true");
  expect(
    screen.getByRole("tab", { name: detailCopy.tabs.configuration })
  ).toBeInTheDocument();
  await u.click(screen.getByRole("tab", { name: detailCopy.tabs.actions }));
  expect(window.location.search).toBe("?tab=actions");
});

test("says when the integration does not exist", async () => {
  mockFetch({
    [URL_DETAIL]: new Response(JSON.stringify({ detail: "missing" }), {
      status: 404,
    }),
  });
  open();
  expect(await screen.findByText(detailCopy.notFound)).toBeInTheDocument();
});

// ── Overview ─────────────────────────────────────────────────────────────────

test("shows the overview and turns the integration off", async () => {
  const fetchMock = mockFetch({
    [URL_DETAIL]: makeDetail(),
    [`PATCH ${URL_DETAIL}`]: makeDetail({ enabled: false }),
    "/api/admin/integrations": [],
  });
  const u = user();
  open();
  const view = await inPanel();
  expect(await view.findByText("Manage issues")).toBeInTheDocument();
  expect(view.getByText("Each user (OAuth)")).toBeInTheDocument();
  expect(view.getByText("admin@example.com")).toBeInTheDocument();
  expect(
    view.getByRole("combobox", { name: "Install setting of Linear" })
  ).toHaveValue(messages.skills.installationPolicy.AVAILABLE.label);

  await u.click(
    screen.getByRole("switch", { name: detailCopy.overview.enabled.title })
  );
  await waitFor(() =>
    expect(requestBody(fetchMock, "PATCH", URL_DETAIL)).toMatchObject({
      enabled: false,
    })
  );
});

test("deletes the integration after a confirmation", async () => {
  const fetchMock = mockFetch({
    [URL_DETAIL]: makeDetail(),
    [`DELETE ${URL_DETAIL}`]: null,
    "/api/admin/integrations": [],
  });
  const u = user();
  open();
  const view = await inPanel();
  await view.findByText("Manage issues");
  await u.click(screen.getByRole("button", { name: detailCopy.overview.menu }));
  await u.click(
    await screen.findByRole("menuitem", {
      name: detailCopy.overview.delete.label,
    })
  );
  const dialog = await screen.findByRole("dialog");
  await u.click(
    within(dialog).getByRole("button", {
      name: detailCopy.overview.delete.confirm,
    })
  );
  await waitFor(() =>
    expect(window.location.pathname).toBe("/admin/integrations")
  );
  expect(
    fetchMock.mock.calls.some(
      ([input, init]) =>
        String(input) === URL_DETAIL && init?.method === "DELETE"
    )
  ).toBe(true);
});

test("disables the controls when the admin cannot manage it", async () => {
  mockFetch({
    [URL_DETAIL]: makeDetail({ can_manage: false, can_delete: false }),
  });
  open();
  const view = await inPanel();
  expect(
    await view.findByText(detailCopy.overview.readOnly)
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: detailCopy.overview.menu })
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("switch", { name: detailCopy.overview.enabled.title })
  ).toHaveAttribute("aria-disabled", "true");
});

test("hides Delete for an app that Onyx provides", async () => {
  mockFetch({ [URL_DETAIL]: makeDetail({ can_delete: false }) });
  const u = user();
  open();
  const view = await inPanel();
  await view.findByText("Manage issues");
  await u.click(screen.getByRole("button", { name: detailCopy.overview.menu }));
  expect(
    await screen.findByRole("menuitem", {
      name: detailCopy.overview.details.edit,
    })
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("menuitem", { name: detailCopy.overview.delete.label })
  ).not.toBeInTheDocument();
});

// ── Configuration ────────────────────────────────────────────────────────────

test("saves the sign-in settings", async () => {
  const fetchMock = mockFetch({
    [URL_DETAIL]: makeDetail(),
    [`PATCH ${URL_DETAIL}`]: makeDetail(),
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const scopes = await view.findByRole("textbox", {
    name: copy.signIn.oauth.scopes.title,
  });
  expect(
    view.getByRole("textbox", { name: copy.signIn.oauth.clientId })
  ).toHaveValue("client-1");
  expect(
    view.getByPlaceholderText(copy.signIn.oauth.clientSecretSaved)
  ).toBeInTheDocument();
  await u.clear(scopes);
  await u.type(scopes, "read write");
  await u.click(
    view.getByRole("switch", {
      name: detailCopy.configuration.alwaysAllow.title,
    })
  );
  await u.click(
    view.getByRole("button", { name: detailCopy.configuration.save })
  );

  await waitFor(() =>
    expect(requestBody(fetchMock, "PATCH", URL_DETAIL)).toEqual({
      auth_mode: "individual",
      auth_method: "oauth2",
      header_template: null,
      oauth_client: {
        provider_mode: "manual",
        authorization_url: "https://linear.app/oauth/authorize",
        token_url: "https://api.linear.app/oauth/token",
        scopes: ["read", "write"],
        additional_params: null,
        pkce: null,
        client_id: "client-1",
        client_secret: null,
      },
      users_can_save_always_allow: false,
    })
  );
});

test("offers the Onyx login sign-in for an MCP server", async () => {
  mockFetch({
    [URL_DETAIL]: makeDetail({
      auth_mode: "individual",
      auth_method: "oauth2",
    }),
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  await u.click(await view.findByRole("combobox", { name: "Sign-in Method" }));
  expect(
    await screen.findByRole("option", { name: "Onyx login" })
  ).toBeInTheDocument();
});

test("sends a changed server URL with the configuration", async () => {
  const fetchMock = mockFetch({
    [URL_DETAIL]: makeDetail({ auth_mode: "none", auth_method: null }),
    [`PATCH ${URL_DETAIL}`]: makeDetail(),
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const url = await view.findByRole("textbox", {
    name: detailCopy.configuration.connection.serverUrl,
  });
  await u.clear(url);
  await u.type(url, "https://mcp.linear.app/v2");
  await u.click(
    view.getByRole("button", { name: detailCopy.configuration.save })
  );
  await waitFor(() =>
    expect(requestBody(fetchMock, "PATCH", URL_DETAIL)).toMatchObject({
      config: {
        shape: "mcp_server",
        server_url: "https://mcp.linear.app/v2",
        transport: "STREAMABLE_HTTP",
      },
    })
  );
});

test("sends an edited OpenAPI schema and rejects one that is not JSON", async () => {
  const spec = { openapi: "3.0.0", info: { title: "Reports" } };
  const fetchMock = mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "openapi",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config: { shape: "openapi", openapi_spec: spec },
    }),
    [`PATCH ${URL_DETAIL}`]: makeDetail(),
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const schema = await view.findByRole("textbox", {
    name: detailCopy.configuration.connection.schema,
  });
  expect(schema).toHaveValue(JSON.stringify(spec, null, 2));
  const save = view.getByRole("button", {
    name: detailCopy.configuration.save,
  });

  await u.clear(schema);
  await u.type(schema, "not json");
  await u.click(save);
  expect(
    view.getByText(detailCopy.configuration.connection.schemaError)
  ).toBeInTheDocument();
  expect(
    fetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")
  ).toBe(false);

  await u.clear(schema);
  await u.click(schema);
  await u.paste('{"openapi":"3.1.0"}');
  await u.click(save);
  await waitFor(() =>
    expect(requestBody(fetchMock, "PATCH", URL_DETAIL)).toMatchObject({
      config: { shape: "openapi", openapi_spec: { openapi: "3.1.0" } },
    })
  );
});

test("connects the organization account with an API key", async () => {
  const shared = makeDetail({
    auth_mode: "shared",
    auth_method: "api_key",
    oauth_client: null,
    header_template: { Authorization: "Bearer {api_key}" },
    credential_fields: [{ key: "api_key", label: "API key", secret: true }],
    organization_status: {
      state: "not_set_up",
      reason: null,
    },
    needs_setup: true,
  });
  const fetchMock = mockFetch({
    [URL_DETAIL]: shared,
    [`PUT ${URL_DETAIL}/organization-connection`]: {
      state: "connected",
      reason: null,
    },
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const key = await view.findByLabelText("API key");
  await u.type(key, "secret-1");
  await u.click(
    view.getByRole("button", {
      name: detailCopy.configuration.organization.connect,
    })
  );
  await waitFor(() =>
    expect(
      requestBody(fetchMock, "PUT", `${URL_DETAIL}/organization-connection`)
    ).toEqual({ fields: { api_key: "secret-1" } })
  );
});

test("shows each header of the template and saves the headers shown", async () => {
  const detail = makeDetail({
    auth_mode: "individual",
    auth_method: "api_key",
    oauth_client: null,
    header_template: {
      "X-Tenant": "{tenant}",
      Authorization: "Bearer {api_key}",
    },
    credential_fields: [
      { key: "tenant", label: "tenant", secret: true },
      { key: "api_key", label: "api key", secret: true },
    ],
  });
  const fetchMock = mockFetch({
    [URL_DETAIL]: detail,
    [`PATCH ${URL_DETAIL}`]: detail,
    [URL_ACTIONS]: NO_ACTIONS,
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const nameLabel = copy.signIn.header.name.title;
  expect(await view.findByLabelText(nameLabel)).toHaveValue("X-Tenant");
  expect(view.getByLabelText(`${nameLabel} 2`)).toHaveValue("Authorization");
  expect(
    view.getByLabelText(`${copy.signIn.header.value.title} 2`)
  ).toHaveValue("Bearer {api_key}");

  await u.click(
    view.getByRole("button", {
      name: copy.signIn.header.remove.replace("{name}", "X-Tenant"),
    })
  );
  await u.click(
    view.getByRole("button", { name: detailCopy.configuration.save })
  );
  await waitFor(() => expect(patchBodies(fetchMock)).toHaveLength(1));
  expect(patchBodies(fetchMock)[0]).toHaveProperty("header_template", {
    Authorization: "Bearer {api_key}",
  });
});

test("shows a header name error on the row that needs it", async () => {
  const detail = makeDetail({
    auth_mode: "individual",
    auth_method: "api_key",
    oauth_client: null,
    header_template: {
      "X-Tenant": "{tenant}",
      Authorization: "Bearer {api_key}",
    },
    credential_fields: [
      { key: "tenant", label: "tenant", secret: true },
      { key: "api_key", label: "api key", secret: true },
    ],
  });
  mockFetch({
    [URL_DETAIL]: detail,
    [URL_ACTIONS]: NO_ACTIONS,
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const nameLabel = copy.signIn.header.name.title;
  await u.clear(await view.findByLabelText(nameLabel));
  await u.click(
    view.getByRole("button", { name: detailCopy.configuration.save })
  );

  const error = await view.findByText(copy.signIn.header.name.error);
  const second = view.getByLabelText(`${nameLabel} 2`);
  expect(
    error.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING
  ).toBeTruthy();
});

function patchBodies(fetchMock: jest.SpyInstance): unknown[] {
  return fetchMock.mock.calls
    .filter(
      ([input, init]) =>
        String(input) === URL_DETAIL && init?.method === "PATCH"
    )
    .map(([, init]) => JSON.parse(String(init?.body)));
}

test("clears a saved client secret from the draft", async () => {
  const fetchMock = mockFetch({
    [URL_DETAIL]: makeDetail(),
    [`PATCH ${URL_DETAIL}`]: makeDetail(),
    [URL_ACTIONS]: NO_ACTIONS,
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const secret = await view.findByLabelText(copy.signIn.oauth.clientSecret);
  await u.type(secret, "secret-2");
  const save = view.getByRole("button", {
    name: detailCopy.configuration.save,
  });
  await u.click(save);
  await waitFor(() => expect(secret).toHaveValue(""));

  await u.click(save);
  await waitFor(() => expect(patchBodies(fetchMock)).toHaveLength(2));
  expect(patchBodies(fetchMock)[1]).toEqual({
    users_can_save_always_allow: true,
  });
});

test("shows a saved schema as the server returns it", async () => {
  const saved = { openapi: "3.1.0" };
  let detail = makeDetail({
    kind: "api",
    shape: "openapi",
    auth_mode: "none",
    auth_method: null,
    oauth_client: null,
    config: { shape: "openapi", openapi_spec: { openapi: "3.0.0" } },
  });
  const fetchMock = mockFetch({
    [URL_DETAIL]: () => detail,
    [`PATCH ${URL_DETAIL}`]: () => {
      detail = { ...detail, config: { shape: "openapi", openapi_spec: saved } };
      return detail;
    },
    [URL_ACTIONS]: NO_ACTIONS,
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const schema = await view.findByRole("textbox", {
    name: detailCopy.configuration.connection.schema,
  });
  await u.clear(schema);
  await u.click(schema);
  await u.paste(JSON.stringify(saved));
  const save = view.getByRole("button", {
    name: detailCopy.configuration.save,
  });
  await u.click(save);
  await waitFor(() =>
    expect(schema).toHaveValue(JSON.stringify(saved, null, 2))
  );

  await u.click(save);
  await waitFor(() => expect(patchBodies(fetchMock)).toHaveLength(2));
  expect(patchBodies(fetchMock)[1]).toEqual({
    users_can_save_always_allow: true,
  });
});

test("sends only Always allow when the sign-in did not change", async () => {
  const fetchMock = mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "openapi",
      auth_mode: "shared",
      auth_method: "api_key",
      oauth_client: null,
      config: { shape: "openapi", openapi_spec: { openapi: "3.0.0" } },
      header_template: { Authorization: "Bearer {api_key}", "X-Org": "{org}" },
    }),
    [`PATCH ${URL_DETAIL}`]: makeDetail(),
    [URL_ACTIONS]: NO_ACTIONS,
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  await u.click(
    await view.findByRole("switch", {
      name: detailCopy.configuration.alwaysAllow.title,
    })
  );
  await u.click(
    view.getByRole("button", { name: detailCopy.configuration.save })
  );
  await waitFor(() =>
    expect(requestBody(fetchMock, "PATCH", URL_DETAIL)).toEqual({
      users_can_save_always_allow: false,
    })
  );
});

test("saves Always allow for an app that Onyx provides", async () => {
  const fetchMock = mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "preset",
      preset_id: "GITHUB",
      auth_mode: "individual",
      auth_method: "oauth2",
      oauth_client: null,
      header_template: null,
      can_delete: false,
      config: { shape: "preset", preset_id: "GITHUB" },
    }),
    "/api/admin/integrations/presets": [
      {
        id: "GITHUB",
        name: "GitHub",
        auth_methods: ["oauth2"],
        required_org_credential_fields: [],
        setup_instructions: null,
      },
    ],
    [`PATCH ${URL_DETAIL}`]: makeDetail(),
    [URL_ACTIONS]: NO_ACTIONS,
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  await u.click(
    await view.findByRole("switch", {
      name: detailCopy.configuration.alwaysAllow.title,
    })
  );
  expect(
    view.queryByLabelText(copy.signIn.oauth.clientId)
  ).not.toBeInTheDocument();
  await u.click(
    view.getByRole("button", { name: detailCopy.configuration.save })
  );
  await waitFor(() =>
    expect(requestBody(fetchMock, "PATCH", URL_DETAIL)).toEqual({
      users_can_save_always_allow: false,
    })
  );
});

test("keeps the other headers and the OAuth options in a sign-in change", async () => {
  const fetchMock = mockFetch({
    [URL_DETAIL]: makeDetail({
      oauth_client: {
        ...makeDetail().oauth_client!,
        additional_params: { audience: "api" },
        pkce: true,
      },
    }),
    [`PATCH ${URL_DETAIL}`]: makeDetail(),
    [URL_ACTIONS]: NO_ACTIONS,
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const scopes = await view.findByRole("textbox", {
    name: copy.signIn.oauth.scopes.title,
  });
  await u.type(scopes, " write");
  await u.click(
    view.getByRole("button", { name: detailCopy.configuration.save })
  );
  await waitFor(() =>
    expect(requestBody(fetchMock, "PATCH", URL_DETAIL)).toMatchObject({
      oauth_client: {
        scopes: ["read", "write"],
        additional_params: { audience: "api" },
        pkce: true,
      },
    })
  );
});

test("keeps every saved header when the API key header changes", async () => {
  const fetchMock = mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "openapi",
      auth_mode: "shared",
      auth_method: "api_key",
      oauth_client: null,
      config: { shape: "openapi", openapi_spec: { openapi: "3.0.0" } },
      header_template: { Authorization: "Bearer {api_key}", "X-Org": "{org}" },
    }),
    [`PATCH ${URL_DETAIL}`]: makeDetail(),
    [URL_ACTIONS]: NO_ACTIONS,
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const value = await view.findByRole("textbox", {
    name: copy.signIn.header.value.title,
  });
  await u.clear(value);
  await u.click(value);
  await u.paste("Token {api_key}");
  await u.click(
    view.getByRole("button", { name: detailCopy.configuration.save })
  );
  await waitFor(() =>
    expect(requestBody(fetchMock, "PATCH", URL_DETAIL)).toMatchObject({
      header_template: { "X-Org": "{org}", Authorization: "Token {api_key}" },
    })
  );
  expect(requestBody(fetchMock, "PATCH", URL_DETAIL)).not.toHaveProperty(
    "credential_fields"
  );
});

test("offers only the provider modes the backend accepts", async () => {
  mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "openapi",
      config: { shape: "openapi", openapi_spec: { openapi: "3.0.0" } },
    }),
    [URL_ACTIONS]: NO_ACTIONS,
  });
  open("configuration");
  const view = await inPanel();
  await view.findByRole("textbox", { name: copy.signIn.oauth.clientId });
  expect(
    view.queryByText(copy.signIn.oauth.providerMode.title)
  ).not.toBeInTheDocument();
});

test("replaces the account settings of a preset", async () => {
  const fetchMock = mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "preset",
      preset_id: "ZENDESK",
      oauth_client: { ...makeDetail().oauth_client!, provider_mode: "preset" },
      config: {
        shape: "preset",
        preset_id: "ZENDESK",
      },
    }),
    "/api/admin/integrations/presets": [
      {
        id: "ZENDESK",
        name: "Zendesk",
        auth_methods: ["oauth2"],
        required_org_credential_fields: [
          { key: "subdomain", label: "Subdomain", secret: false },
          { key: "client_id", label: "Client ID", secret: false },
        ],
        setup_instructions: null,
      },
    ],
    [`PATCH ${URL_DETAIL}`]: makeDetail(),
    [URL_ACTIONS]: NO_ACTIONS,
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  await u.type(await view.findByLabelText("Subdomain"), "acme");
  const save = view.getByRole("button", {
    name: detailCopy.configuration.save,
  });
  await u.click(save);
  expect(
    view.getByText(detailCopy.configuration.preset.credentialRequired)
  ).toBeInTheDocument();
  await u.type(view.getByLabelText("Client ID"), "zd-client");
  await u.click(save);
  await waitFor(() =>
    expect(requestBody(fetchMock, "PATCH", URL_DETAIL)).toMatchObject({
      users_can_save_always_allow: true,
      config: {
        shape: "preset",
        preset_id: "ZENDESK",
        organization_credentials: { subdomain: "acme", client_id: "zd-client" },
      },
    })
  );
});

test("keeps a configuration draft across a tab switch", async () => {
  mockFetch({ [URL_DETAIL]: makeDetail(), [URL_ACTIONS]: NO_ACTIONS });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const scopes = await view.findByRole("textbox", {
    name: copy.signIn.oauth.scopes.title,
  });
  await u.type(scopes, " write");
  await u.click(screen.getByRole("tab", { name: detailCopy.tabs.overview }));
  await u.click(
    screen.getByRole("tab", { name: detailCopy.tabs.configuration })
  );
  expect(
    (await inPanel()).getByRole("textbox", {
      name: copy.signIn.oauth.scopes.title,
    })
  ).toHaveValue("read write");
});

test("renames the integration and changes its description", async () => {
  const fetchMock = mockFetch({
    [URL_DETAIL]: makeDetail(),
    [`PATCH ${URL_DETAIL}`]: makeDetail({
      name: "Linear EU",
      description: "EU issues",
    }),
    [URL_ACTIONS]: NO_ACTIONS,
    "/api/admin/integrations": [],
  });
  const u = user();
  open();
  const view = await inPanel();
  await view.findByText("Manage issues");
  await u.click(screen.getByRole("button", { name: detailCopy.overview.menu }));
  await u.click(
    await screen.findByRole("menuitem", {
      name: detailCopy.overview.details.edit,
    })
  );
  const dialog = await screen.findByRole("dialog");
  const name = within(dialog).getByRole("textbox", {
    name: detailCopy.overview.details.name,
  });
  await u.clear(name);
  await u.type(name, "Linear EU");
  const description = within(dialog).getByRole("textbox", {
    name: detailCopy.overview.details.description,
  });
  await u.clear(description);
  await u.type(description, "EU issues");
  await u.click(
    within(dialog).getByRole("button", {
      name: detailCopy.overview.details.save,
    })
  );
  await waitFor(() =>
    expect(requestBody(fetchMock, "PATCH", URL_DETAIL)).toMatchObject({
      name: "Linear EU",
      description: "EU issues",
    })
  );
});
