import { PointerEventsCheckLevel } from "@testing-library/user-event";
import {
  act,
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
import type {
  GraphQLConfig,
  IntegrationConfigView,
  OpenApiConfigView,
} from "@/lib/integrations/types";

const copy = messages.admin.integrations;
const detailCopy = copy.detail;

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => window.location.pathname,
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

let mockGlobalHolder = false;
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({
    isGlobalHolder: mockGlobalHolder,
    isScopedManager: false,
  }),
}));

const URL_DETAIL = "/api/admin/integrations/1";
const URL_ACTIONS = `${URL_DETAIL}/actions`;
const NO_ACTIONS = { default_policy: null, actions: [] };
const OPENAPI_VIEW: OpenApiConfigView = {
  shape: "openapi",
  openapi_document: '{"openapi": "3.0.0"}',
  base_url: "https://reports.example.com",
  endpoints: ["GET /reports List reports"],
  skipped: [],
};

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

beforeEach(() => {
  mockGlobalHolder = false;
});
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

test("lists the URL patterns of a URL-pattern app", async () => {
  mockFetch({
    [URL_DETAIL]: makeDetail({
      shape: "custom",
      config: {
        shape: "custom",
        upstream_url_patterns: ["https://api.example.com/v1/*"],
      },
    }),
  });
  open();
  const view = await inPanel();
  expect(
    await view.findByText(detailCopy.overview.urlPatternApp.title)
  ).toBeInTheDocument();
  expect(view.getByText("https://api.example.com/v1/*")).toBeInTheDocument();
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
  mockGlobalHolder = true;
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

test("offers Onyx login only when each user signs in", async () => {
  mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "graphql",
      auth_mode: "individual",
      auth_method: "onyx_login",
      oauth_client: null,
      config: GRAPHQL_CONFIG,
    }),
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const method = await view.findByRole("combobox", {
    name: copy.signIn.method.title,
  });
  expect(method).toHaveValue(copy.signIn.method.onyxLogin);

  await u.click(view.getByRole("combobox", { name: copy.signIn.mode.title }));
  await u.click(
    await screen.findByRole("option", { name: copy.signIn.mode.shared })
  );

  expect(method).toHaveValue(copy.signIn.method.oauth2);
  await u.click(method);
  expect(
    (await screen.findAllByRole("option")).map((option) => option.textContent)
  ).not.toContain(copy.signIn.method.onyxLogin);
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

test("sends an edited endpoint line, or a reimported spec", async () => {
  const REIMPORTED = '{"openapi": "3.0.0", "components": {}}';
  const fetchMock = mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "openapi",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config: OPENAPI_VIEW,
    }),
    [`PATCH ${URL_DETAIL}`]: makeDetail(),
    "POST /api/admin/integrations/openapi-import": {
      ...OPENAPI_VIEW,
      openapi_document: REIMPORTED,
    },
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const endpoints = await view.findByRole("textbox", {
    name: copy.add.rest.endpoints.title,
  });
  expect(endpoints).toHaveValue("GET /reports List reports");
  const save = view.getByRole("button", {
    name: detailCopy.configuration.save,
  });

  await u.clear(endpoints);
  await u.type(endpoints, "GET /reports List all reports");
  // The tool appends paths that start with "/".
  await u.type(
    view.getByRole("textbox", { name: copy.add.rest.baseUrl.title }),
    "/"
  );
  await u.click(save);
  await waitFor(() =>
    expect(requestBody(fetchMock, "PATCH", URL_DETAIL)).toMatchObject({
      config: {
        shape: "openapi",
        openapi_document: OPENAPI_VIEW.openapi_document,
        base_url: "https://reports.example.com",
        endpoints: ["GET /reports List all reports"],
      },
    })
  );

  // A reimport that changes only the document is still a change.
  await u.type(
    view.getByRole("textbox", { name: copy.add.rest.import.url }),
    "https://reports.example.com/openapi.json"
  );
  await u.click(
    view.getByRole("button", { name: copy.add.rest.import.submit })
  );
  await waitFor(() =>
    expect(endpoints).toHaveValue("GET /reports List reports")
  );
  await u.click(save);
  await waitFor(() =>
    expect(patchBodies(fetchMock).at(-1)).toMatchObject({
      config: {
        shape: "openapi",
        openapi_document: REIMPORTED,
        base_url: "https://reports.example.com",
        endpoints: ["GET /reports List reports"],
      },
    })
  );
});

test("resolves a relative server of a spec imported from a URL", async () => {
  mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "openapi",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config: OPENAPI_VIEW,
    }),
    "POST /api/admin/integrations/openapi-import": {
      ...OPENAPI_VIEW,
      base_url: "/api/v3",
    },
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  await u.type(
    await view.findByRole("textbox", { name: copy.add.rest.import.url }),
    "https://pets.example.com/api/v3/openapi.json"
  );
  await u.click(
    view.getByRole("button", { name: copy.add.rest.import.submit })
  );

  await waitFor(() =>
    expect(
      view.getByRole("textbox", { name: copy.add.rest.baseUrl.title })
    ).toHaveValue("https://pets.example.com/api/v3")
  );
});

test("a server URL with a port variable and no default stays editable", async () => {
  mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "openapi",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config: OPENAPI_VIEW,
    }),
    "POST /api/admin/integrations/openapi-import": {
      ...OPENAPI_VIEW,
      base_url: "https://api.example.com:{port}/v1",
    },
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  await u.type(
    await view.findByRole("textbox", { name: copy.add.rest.import.url }),
    "https://pets.example.com/openapi.json"
  );
  await u.click(
    view.getByRole("button", { name: copy.add.rest.import.submit })
  );

  await waitFor(() =>
    expect(
      view.getByRole("textbox", { name: copy.add.rest.baseUrl.title })
    ).toHaveValue("https://api.example.com:{port}/v1")
  );
});

test("a refused REST upload blocks Save until a spec imports", async () => {
  mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "openapi",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config: OPENAPI_VIEW,
    }),
    "POST /api/admin/integrations/openapi-import": OPENAPI_VIEW,
  });
  const big = new File(["x"], "openapi.json");
  Object.defineProperty(big, "size", { value: 5 * 1024 * 1024 + 1 });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const input = await waitFor(() => {
    const found =
      activePanel().querySelector<HTMLInputElement>('input[type="file"]');
    if (!found) throw new Error("No file input");
    return found;
  });
  await u.upload(input, big);
  expect(await view.findByText(copy.add.api.tooLarge)).toBeInTheDocument();
  const save = view.getByRole("button", {
    name: detailCopy.configuration.save,
  });
  expect(save).toBeDisabled();

  await u.type(
    view.getByRole("textbox", { name: copy.add.rest.import.url }),
    "https://pets.example.com/openapi.json"
  );
  await u.click(
    view.getByRole("button", { name: copy.add.rest.import.submit })
  );

  await waitFor(() =>
    expect(view.queryByText(copy.add.api.tooLarge)).not.toBeInTheDocument()
  );
  expect(save).toBeEnabled();
});

test("a refused REST upload can be discarded to keep the current spec", async () => {
  mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "openapi",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config: OPENAPI_VIEW,
    }),
  });
  const big = new File(["x"], "openapi.json");
  Object.defineProperty(big, "size", { value: 5 * 1024 * 1024 + 1 });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const save = await view.findByRole("button", {
    name: detailCopy.configuration.save,
  });
  const input =
    activePanel().querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("No file input");
  await u.upload(input, big);
  expect(await view.findByText(copy.add.api.tooLarge)).toBeInTheDocument();
  expect(save).toBeDisabled();

  await u.click(view.getByRole("button", { name: copy.add.api.upload.remove }));

  expect(view.queryByText(copy.add.api.tooLarge)).not.toBeInTheDocument();
  expect(save).toBeEnabled();
});

test("discarding a refused REST upload keeps a later URL import error", async () => {
  mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "openapi",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config: OPENAPI_VIEW,
    }),
    "POST /api/admin/integrations/openapi-import": new Response(
      JSON.stringify({ detail: "Could not fetch the spec" }),
      { status: 400 }
    ),
  });
  const big = new File(["x"], "openapi.json");
  Object.defineProperty(big, "size", { value: 5 * 1024 * 1024 + 1 });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const save = await view.findByRole("button", {
    name: detailCopy.configuration.save,
  });
  const input =
    activePanel().querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("No file input");
  await u.upload(input, big);
  expect(await view.findByText(copy.add.api.tooLarge)).toBeInTheDocument();

  await u.type(
    view.getByRole("textbox", { name: copy.add.rest.import.url }),
    "https://pets.example.com/openapi.json"
  );
  await u.click(
    view.getByRole("button", { name: copy.add.rest.import.submit })
  );
  expect(await view.findByText("Could not fetch the spec")).toBeInTheDocument();

  const remove = view.queryByRole("button", {
    name: copy.add.api.upload.remove,
  });
  if (remove) await u.click(remove);
  expect(view.getByText("Could not fetch the spec")).toBeInTheDocument();
  expect(save).toBeDisabled();
});

/** Makes the next file read fail, as an unreadable file does. */
function failNextRead(): void {
  jest
    .spyOn(FileReader.prototype, "readAsText")
    .mockImplementationOnce(function (this: FileReader) {
      setTimeout(() => this.dispatchEvent(new ProgressEvent("error")));
    });
}

test.each([
  ["a blank", false],
  ["an unreadable", true],
])(
  "%s REST upload blocks Save until it is discarded",
  async (_, unreadable) => {
    mockFetch({
      [URL_DETAIL]: makeDetail({
        kind: "api",
        shape: "openapi",
        auth_mode: "none",
        auth_method: null,
        oauth_client: null,
        config: OPENAPI_VIEW,
      }),
    });
    if (unreadable) failNextRead();
    const u = user();
    open("configuration");
    const view = await inPanel();
    const save = await view.findByRole("button", {
      name: detailCopy.configuration.save,
    });
    const input =
      activePanel().querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("No file input");
    await u.upload(input, new File(unreadable ? ["{}"] : [], "openapi.json"));

    expect(
      await view.findByText(copy.add.rest.import.failed)
    ).toBeInTheDocument();
    expect(save).toBeDisabled();

    await u.click(
      view.getByRole("button", { name: copy.add.api.upload.remove })
    );
    expect(
      view.queryByText(copy.add.rest.import.failed)
    ).not.toBeInTheDocument();
    expect(save).toBeEnabled();
  }
);

test("a failed spec import blocks Save until the import is discarded", async () => {
  mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "openapi",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config: OPENAPI_VIEW,
    }),
    "POST /api/admin/integrations/openapi-import": new Response(
      JSON.stringify({ detail: "Could not fetch the spec" }),
      { status: 400 }
    ),
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const save = await view.findByRole("button", {
    name: detailCopy.configuration.save,
  });
  const baseUrl = view.getByRole("textbox", {
    name: copy.add.rest.baseUrl.title,
  });
  await u.clear(baseUrl);
  await u.type(baseUrl, "https://new.example.com");
  expect(save).toBeEnabled();

  const specUrl = view.getByRole("textbox", { name: copy.add.rest.import.url });
  await u.type(specUrl, "https://new.example.com/openapi.json");
  await u.click(
    view.getByRole("button", { name: copy.add.rest.import.submit })
  );

  expect(await view.findByText("Could not fetch the spec")).toBeInTheDocument();
  expect(save).toBeDisabled();

  await u.clear(specUrl);
  expect(view.queryByText("Could not fetch the spec")).not.toBeInTheDocument();
  expect(save).toBeEnabled();
});

test("keeps the Base URL when a spec imported from a URL has no single server", async () => {
  mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "openapi",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config: OPENAPI_VIEW,
    }),
    "POST /api/admin/integrations/openapi-import": {
      ...OPENAPI_VIEW,
      endpoints: ["GET /pets List pets"],
      base_url: "",
    },
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const endpoints = await view.findByRole("textbox", {
    name: copy.add.rest.endpoints.title,
  });
  await u.type(
    view.getByRole("textbox", { name: copy.add.rest.import.url }),
    "https://docs.example.com/openapi.json"
  );
  await u.click(
    view.getByRole("button", { name: copy.add.rest.import.submit })
  );

  await waitFor(() => expect(endpoints).toHaveValue("GET /pets List pets"));
  expect(
    view.getByRole("textbox", { name: copy.add.rest.baseUrl.title })
  ).toHaveValue(OPENAPI_VIEW.base_url);
});

test("sends the stored lines unchanged when only the Base URL changes", async () => {
  // The backend keeps the operation of a line sent as shown, also one whose
  // line does not parse back to it.
  const config: OpenApiConfigView = {
    ...OPENAPI_VIEW,
    endpoints: ["GET /reports?search term List reports", "GET /ping "],
  };
  const fetchMock = mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "openapi",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config,
    }),
    [`PATCH ${URL_DETAIL}`]: makeDetail(),
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const baseUrl = await view.findByRole("textbox", {
    name: copy.add.rest.baseUrl.title,
  });
  await u.clear(baseUrl);
  await u.type(baseUrl, "https://staging.example.com");
  await u.click(
    view.getByRole("button", { name: detailCopy.configuration.save })
  );

  await waitFor(() =>
    expect(requestBody(fetchMock, "PATCH", URL_DETAIL)).toMatchObject({
      config: {
        shape: "openapi",
        openapi_document: config.openapi_document,
        base_url: "https://staging.example.com",
        endpoints: config.endpoints,
      },
    })
  );
});

test("refuses a Base URL that is not a URL", async () => {
  const fetchMock = mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "openapi",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config: OPENAPI_VIEW,
    }),
    [`PATCH ${URL_DETAIL}`]: makeDetail(),
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const baseUrl = await view.findByRole("textbox", {
    name: copy.add.rest.baseUrl.title,
  });
  await u.clear(baseUrl);
  await u.type(baseUrl, "reports.example.com");
  await u.click(
    view.getByRole("button", { name: detailCopy.configuration.save })
  );

  expect(
    await view.findByText(copy.add.rest.baseUrl.required)
  ).toBeInTheDocument();
  expect(
    fetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")
  ).toBe(false);
});

test("keeps the Base URL when an uploaded spec has a relative server", async () => {
  mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "openapi",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config: OPENAPI_VIEW,
    }),
    "POST /api/admin/integrations/openapi-import": {
      ...OPENAPI_VIEW,
      endpoints: ["GET /pets List pets"],
      base_url: "/",
    },
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const endpoints = await view.findByRole("textbox", {
    name: copy.add.rest.endpoints.title,
  });
  const input =
    activePanel().querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("No file input");
  await u.upload(input, new File(['{"openapi": "3.0.0"}'], "openapi.json"));

  await waitFor(() => expect(endpoints).toHaveValue("GET /pets List pets"));
  expect(
    view.getByRole("textbox", { name: copy.add.rest.baseUrl.title })
  ).toHaveValue(OPENAPI_VIEW.base_url);
});

test("lists the operations that a reimported spec skipped", async () => {
  const skipped = "POST /reports: the request body is not JSON";
  mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "openapi",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config: OPENAPI_VIEW,
    }),
    "POST /api/admin/integrations/openapi-import": {
      ...OPENAPI_VIEW,
      skipped: [skipped],
    },
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  await u.type(
    await view.findByRole("textbox", { name: copy.add.rest.import.url }),
    "https://reports.example.com/openapi.json"
  );
  await u.click(
    view.getByRole("button", { name: copy.add.rest.import.submit })
  );
  await u.click(
    await view.findByRole("button", {
      name: `Expand ${copy.add.detected.skippedTitle}`,
    })
  );
  expect(await view.findByText(skipped)).toBeInTheDocument();
});

const GRAPHQL_CONFIG: GraphQLConfig = {
  shape: "graphql",
  endpoint_url: "https://api.example.com/graphql",
  graphql_schema: "type Query { a: Int }",
};

test.each<[IntegrationConfigView, string]>([
  [OPENAPI_VIEW, "openapi.json"],
  [GRAPHQL_CONFIG, "schema.graphql"],
])(
  "does not read an upload over the size limit (%#)",
  async (config, fileName) => {
    mockFetch({
      [URL_DETAIL]: makeDetail({
        kind: "api",
        shape: config.shape,
        auth_mode: "none",
        auth_method: null,
        oauth_client: null,
        config,
      }),
    });
    const readAsText = jest.spyOn(FileReader.prototype, "readAsText");
    const big = new File(["x"], fileName);
    Object.defineProperty(big, "size", { value: 5 * 1024 * 1024 + 1 });
    const u = user();
    open("configuration");
    const view = await inPanel();
    await view.findByRole("button", { name: detailCopy.configuration.save });
    const input =
      activePanel().querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("No file input");
    await u.upload(input, big);

    expect(await view.findByText(copy.add.api.tooLarge)).toBeInTheDocument();
    expect(readAsText).not.toHaveBeenCalled();
  }
);

test("blocks Save after a refused schema upload until the schema fits", async () => {
  mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "graphql",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config: GRAPHQL_CONFIG,
    }),
  });
  const big = new File(["x"], "schema.graphql");
  Object.defineProperty(big, "size", { value: 5 * 1024 * 1024 + 1 });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const save = await view.findByRole("button", {
    name: detailCopy.configuration.save,
  });
  const input =
    activePanel().querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("No file input");
  await u.upload(input, big);

  expect(await view.findByText(copy.add.api.tooLarge)).toBeInTheDocument();
  expect(save).toBeDisabled();

  await u.type(
    view.getByRole("textbox", { name: copy.add.graphql.schema.title }),
    " "
  );
  await waitFor(() => expect(save).toBeEnabled());
});

test("a blank schema upload blocks Save until it is cleared", async () => {
  mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "graphql",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config: GRAPHQL_CONFIG,
    }),
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const save = await view.findByRole("button", {
    name: detailCopy.configuration.save,
  });
  const input =
    activePanel().querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("No file input");
  await u.upload(input, new File([], "schema.graphql"));

  expect(
    await view.findByText(copy.add.graphql.schema.required)
  ).toBeInTheDocument();
  expect(save).toBeDisabled();

  await u.click(view.getByRole("button", { name: "Clear file" }));
  await waitFor(() => expect(save).toBeEnabled());
  expect(
    view.getByRole("textbox", { name: copy.add.graphql.schema.title })
  ).toHaveValue(GRAPHQL_CONFIG.graphql_schema);
});

test("an unreadable schema upload blocks Save", async () => {
  mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "graphql",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config: GRAPHQL_CONFIG,
    }),
  });
  failNextRead();
  const u = user();
  open("configuration");
  const view = await inPanel();
  const save = await view.findByRole("button", {
    name: detailCopy.configuration.save,
  });
  const input =
    activePanel().querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("No file input");
  await u.upload(input, new File(["type Query { a: Int }"], "schema.graphql"));

  expect(
    await view.findByText(copy.add.graphql.schema.required)
  ).toBeInTheDocument();
  expect(save).toBeDisabled();
});

test("a schema loaded from the endpoint clears a refused upload", async () => {
  const loaded = "type Query { b: Int }";
  mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "graphql",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config: GRAPHQL_CONFIG,
    }),
    "POST /api/admin/integrations/graphql-introspect": {
      ...GRAPHQL_CONFIG,
      graphql_schema: loaded,
    },
  });
  const big = new File(["x"], "schema.graphql");
  Object.defineProperty(big, "size", { value: 5 * 1024 * 1024 + 1 });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const save = await view.findByRole("button", {
    name: detailCopy.configuration.save,
  });
  const input =
    activePanel().querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("No file input");
  await u.upload(input, big);
  expect(await view.findByText(copy.add.api.tooLarge)).toBeInTheDocument();

  await u.click(
    view.getByRole("button", { name: copy.add.graphql.introspect.submit })
  );

  await waitFor(() =>
    expect(
      view.getByRole("textbox", { name: copy.add.graphql.schema.title })
    ).toHaveValue(loaded)
  );
  expect(view.queryByText(copy.add.api.tooLarge)).not.toBeInTheDocument();
  expect(save).toBeEnabled();
});

test("a failed schema load blocks Save until the endpoint URL changes", async () => {
  mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "graphql",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config: GRAPHQL_CONFIG,
    }),
    "POST /api/admin/integrations/graphql-introspect": new Response(
      JSON.stringify({ detail: "Could not load the schema" }),
      { status: 400 }
    ),
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const save = await view.findByRole("button", {
    name: detailCopy.configuration.save,
  });
  const endpoint = view.getByRole("textbox", {
    name: copy.add.graphql.endpointUrl.title,
  });
  await u.clear(endpoint);
  await u.type(endpoint, "https://new.example.com/graphql");
  await u.click(
    view.getByRole("button", { name: copy.add.graphql.introspect.submit })
  );

  expect(
    await view.findByText("Could not load the schema")
  ).toBeInTheDocument();
  expect(save).toBeDisabled();

  await u.type(endpoint, "2");
  expect(view.queryByText("Could not load the schema")).not.toBeInTheDocument();
  expect(save).toBeEnabled();
  expect(
    view.getByRole("textbox", { name: copy.add.graphql.schema.title })
  ).toHaveValue(GRAPHQL_CONFIG.graphql_schema);
});

// Two UTF-8 bytes per character: over 5 MB in bytes, under it in characters.
const OVERSIZED_TEXT = "é".repeat(2.5 * 1024 * 1024 + 1);

test.each<[IntegrationConfigView, () => string]>([
  [OPENAPI_VIEW, () => copy.add.rest.import.upload],
  [GRAPHQL_CONFIG, () => copy.add.graphql.schema.upload],
  [GRAPHQL_CONFIG, () => copy.add.graphql.schema.title],
])("refuses pasted text over the size limit (%#)", async (config, target) => {
  const fetchMock = mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: config.shape,
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config,
    }),
    [URL_ACTIONS]: NO_ACTIONS,
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  await view.findByRole("button", { name: detailCopy.configuration.save });
  const control =
    view.queryByRole("button", { name: target() }) ??
    view.getByRole("textbox", { name: target() });
  await u.click(control);
  await u.paste(OVERSIZED_TEXT);

  expect(await view.findByText(copy.add.api.tooLarge)).toBeInTheDocument();
  if (config.shape === "graphql") {
    expect(
      view.getByRole("textbox", { name: copy.add.graphql.schema.title })
    ).toHaveValue(GRAPHQL_CONFIG.graphql_schema);
  }
  expect(
    fetchMock.mock.calls.some(([input]) =>
      String(input).includes("openapi-import")
    )
  ).toBe(false);
});

test("blocks Save while a spec import runs", async () => {
  let finishImport: (view: OpenApiConfigView) => void = () => undefined;
  mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "openapi",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config: OPENAPI_VIEW,
    }),
    "POST /api/admin/integrations/openapi-import": () =>
      new Promise<OpenApiConfigView>((resolve) => {
        finishImport = resolve;
      }),
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const save = await view.findByRole("button", {
    name: detailCopy.configuration.save,
  });
  await u.type(
    view.getByRole("textbox", { name: copy.add.rest.import.url }),
    "https://reports.example.com/openapi.json"
  );
  await u.click(
    view.getByRole("button", { name: copy.add.rest.import.submit })
  );
  await waitFor(() => expect(save).toBeDisabled());

  finishImport(OPENAPI_VIEW);
  await waitFor(() => expect(save).toBeEnabled());
});

test("blocks Save while a schema file is read", async () => {
  let finishRead: () => void = () => undefined;
  jest
    .spyOn(FileReader.prototype, "readAsText")
    .mockImplementation(function (this: FileReader) {
      finishRead = () => {
        Object.defineProperty(this, "result", {
          value: "type Query { b: Int }",
        });
        this.onload?.(new ProgressEvent("load") as ProgressEvent<FileReader>);
      };
    });
  mockFetch({
    [URL_DETAIL]: makeDetail({
      kind: "api",
      shape: "graphql",
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
      config: GRAPHQL_CONFIG,
    }),
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const save = await view.findByRole("button", {
    name: detailCopy.configuration.save,
  });
  const input =
    activePanel().querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("No file input");
  await u.upload(input, new File(["ignored"], "schema.graphql"));
  await waitFor(() => expect(save).toBeDisabled());

  act(() => finishRead());
  await waitFor(() => expect(save).toBeEnabled());
  expect(
    view.getByRole("textbox", { name: copy.add.graphql.schema.title })
  ).toHaveValue("type Query { b: Int }");
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

test("keeps the saved spec as the server returns it", async () => {
  const saved = {
    ...OPENAPI_VIEW,
    openapi_document: "openapi: 3.1.0\n",
    endpoints: ["GET /reports?limit List all reports"],
  };
  let detail = makeDetail({
    kind: "api",
    shape: "openapi",
    auth_mode: "none",
    auth_method: null,
    oauth_client: null,
    config: OPENAPI_VIEW,
  });
  const fetchMock = mockFetch({
    [URL_DETAIL]: () => detail,
    [`PATCH ${URL_DETAIL}`]: () => {
      detail = { ...detail, config: saved };
      return detail;
    },
    [URL_ACTIONS]: NO_ACTIONS,
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const view = await inPanel();
  const endpoints = await view.findByRole("textbox", {
    name: copy.add.rest.endpoints.title,
  });
  await u.clear(endpoints);
  await u.type(endpoints, "GET /reports List all reports");
  const save = view.getByRole("button", {
    name: detailCopy.configuration.save,
  });
  await u.click(save);
  await waitFor(() =>
    expect(endpoints).toHaveValue("GET /reports?limit List all reports")
  );

  // The stored spec, not the one sent, is the base of the next save.
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
      config: OPENAPI_VIEW,
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
        setup_steps: [],
        setup_url: null,
        callback_url: null,
        scopes: [],
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
      config: OPENAPI_VIEW,
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
      config: OPENAPI_VIEW,
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
        setup_steps: [],
        setup_url: null,
        callback_url: null,
        scopes: [],
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
