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
} from "@/sections/integrations/__tests__/integrationFixtures";

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
  expect(await screen.findByText("Manage issues")).toBeInTheDocument();
  expect(screen.getByText("Each user (OAuth)")).toBeInTheDocument();
  expect(screen.getByText("admin@example.com")).toBeInTheDocument();
  expect(
    screen.getByText("Organization library, available")
  ).toBeInTheDocument();

  await u.click(
    screen.getByRole("switch", { name: detailCopy.overview.enabled.title })
  );
  await waitFor(() =>
    expect(requestBody(fetchMock, "PATCH", URL_DETAIL)).toEqual({
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
  await screen.findByText("Manage issues");
  await u.click(
    screen.getByRole("button", { name: detailCopy.overview.delete.label })
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
  mockFetch({ [URL_DETAIL]: makeDetail({ can_manage: false }) });
  open();
  expect(
    await screen.findByText(detailCopy.overview.readOnly)
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: detailCopy.overview.delete.label })
  ).toBeDisabled();
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
  const scopes = await screen.findByRole("textbox", {
    name: copy.signIn.oauth.scopes.title,
  });
  expect(
    screen.getByRole("textbox", { name: copy.signIn.oauth.clientId })
  ).toHaveValue("client-1");
  expect(
    screen.getByPlaceholderText(copy.signIn.oauth.clientSecretSaved)
  ).toBeInTheDocument();
  await u.clear(scopes);
  await u.type(scopes, "read write");
  await u.click(
    screen.getByRole("switch", {
      name: detailCopy.configuration.alwaysAllow.title,
    })
  );
  await u.click(
    screen.getByRole("button", { name: detailCopy.configuration.save })
  );

  await waitFor(() =>
    expect(requestBody(fetchMock, "PATCH", URL_DETAIL)).toEqual({
      auth_mode: "individual",
      auth_method: "oauth2",
      credential_fields: null,
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

test("sends a changed server URL with the configuration", async () => {
  const fetchMock = mockFetch({
    [URL_DETAIL]: makeDetail({ auth_mode: "none", auth_method: null }),
    [`PATCH ${URL_DETAIL}`]: makeDetail(),
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const url = await screen.findByRole("textbox", {
    name: detailCopy.configuration.connection.serverUrl,
  });
  await u.clear(url);
  await u.type(url, "https://mcp.linear.app/v2");
  await u.click(
    screen.getByRole("button", { name: detailCopy.configuration.save })
  );
  await waitFor(() =>
    expect(requestBody(fetchMock, "PATCH", URL_DETAIL)).toEqual(
      expect.objectContaining({
        auth_mode: "none",
        config: {
          shape: "mcp_server",
          server_url: "https://mcp.linear.app/v2",
          transport: "STREAMABLE_HTTP",
        },
      })
    )
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
  const schema = await screen.findByRole("textbox", {
    name: detailCopy.configuration.connection.schema,
  });
  expect(schema).toHaveValue(JSON.stringify(spec, null, 2));
  const save = screen.getByRole("button", {
    name: detailCopy.configuration.save,
  });

  await u.clear(schema);
  await u.type(schema, "not json");
  await u.click(save);
  expect(
    screen.getByText(detailCopy.configuration.connection.schemaError)
  ).toBeInTheDocument();
  expect(
    fetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")
  ).toBe(false);

  await u.clear(schema);
  await u.click(schema);
  await u.paste('{"openapi":"3.1.0"}');
  await u.click(save);
  await waitFor(() =>
    expect(requestBody(fetchMock, "PATCH", URL_DETAIL)).toEqual(
      expect.objectContaining({
        config: { shape: "openapi", openapi_spec: { openapi: "3.1.0" } },
      })
    )
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
      moving_credentials: false,
    },
    needs_setup: true,
  });
  const fetchMock = mockFetch({
    [URL_DETAIL]: shared,
    [`PUT ${URL_DETAIL}/organization-connection`]: {
      state: "connected",
      reason: null,
      moving_credentials: false,
    },
    "/api/admin/integrations": [],
  });
  const u = user();
  open("configuration");
  const key = await screen.findByLabelText("API key");
  await u.type(key, "secret-1");
  await u.click(
    screen.getByRole("button", {
      name: detailCopy.configuration.organization.connect,
    })
  );
  await waitFor(() =>
    expect(
      requestBody(fetchMock, "PUT", `${URL_DETAIL}/organization-connection`)
    ).toEqual({ fields: { api_key: "secret-1" } })
  );
});
