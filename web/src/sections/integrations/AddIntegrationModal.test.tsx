import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { PointerEventsCheckLevel } from "@testing-library/user-event";
import AddIntegrationModal, {
  type AddIntegrationStart,
} from "@/sections/integrations/AddIntegrationModal";
import messages from "@/i18n/messages/en.json";
import {
  makeDetail,
  makeIntegration,
  mockFetch,
  requestBody,
} from "@tests/setup/integrationTestUtils";

const copy = messages.admin.integrations;
const add = copy.add;
let mockGlobalHolder = true;
const mockProbe = jest.fn();

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => window.location.pathname,
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({
    isGlobalHolder: mockGlobalHolder,
    isScopedManager: !mockGlobalHolder,
  }),
}));
jest.mock("@/lib/mcp/svc", () => ({
  streamMCPServerProbe: (...args: unknown[]) => mockProbe(...args),
}));

const OAUTH_PROBE = {
  kind: "oauth",
  transport: "SSE",
  discovery: {
    status: "metadata_found",
    supports_automatic_registration: true,
    supports_client_metadata: null,
    authorization_endpoint: "https://mcp.example.com/authorize",
    token_endpoint: "https://mcp.example.com/token",
  },
};

const GITHUB_PRESET = {
  id: "github",
  name: "GitHub",
  auth_methods: ["oauth2"],
  required_org_credential_fields: [
    { key: "org", label: "GitHub organization", secret: false },
  ],
  setup_steps: ["Create a GitHub OAuth app.", "Paste the Client ID."],
  setup_url: "https://github.com/settings/developers",
  callback_url: "https://onyx.example.com/craft/v1/apps/oauth/callback",
  scopes: ["repo", "read:org"],
};

function failure(status: number): Response {
  return new Response(JSON.stringify({ detail: "No" }), { status });
}

beforeEach(() => {
  window.history.replaceState(null, "", "/admin/integrations");
  mockProbe.mockReset();
  mockGlobalHolder = true;
});
afterEach(() => jest.restoreAllMocks());

function open(start: AddIntegrationStart) {
  // Selects and the modal animate in with pointer-events off.
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  const onClose = jest.fn();
  render(<AddIntegrationModal from="admin" start={start} onClose={onClose} />);
  return { user, onClose };
}

async function fillConnect(
  user: ReturnType<typeof setupUser>,
  name: string,
  urlLabel: string,
  url: string
): Promise<void> {
  await user.type(screen.getByRole("textbox", { name: add.name.title }), name);
  await user.type(screen.getByRole("textbox", { name: urlLabel }), url);
  await user.click(screen.getByRole("button", { name: add.continue }));
}

async function submit(user: ReturnType<typeof setupUser>): Promise<void> {
  await user.click(await screen.findByRole("button", { name: /^Add$/ }));
}

// ── MCP server ───────────────────────────────────────────────────────────────

describe("MCP server", () => {
  test("checks the server on Continue and preselects the detected sign-in", async () => {
    mockProbe.mockResolvedValue(OAUTH_PROBE);
    const fetchMock = mockFetch({
      "POST /api/admin/integrations": makeDetail({ id: 12 }),
      "/api/admin/integrations": [],
    });
    const { user } = open({ kind: "mcp_server" });
    await fillConnect(
      user,
      "Docs",
      add.mcp.url.title,
      "https://mcp.example.com/mcp"
    );

    expect(await screen.findByText(add.mcp.probe.oauth)).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: copy.signIn.mode.title })
    ).toHaveValue(copy.signIn.mode.individual);
    await submit(user);

    await waitFor(() =>
      expect(
        requestBody(fetchMock, "POST", "/api/admin/integrations")
      ).toMatchObject({
        for_organization: false,
        name: "Docs",
        description: null,
        auth_mode: "individual",
        auth_method: "oauth2",
        oauth_client: { provider_mode: "discovery" },
        config: {
          shape: "mcp_server",
          server_url: "https://mcp.example.com/mcp",
          transport: "SSE",
        },
      })
    );
    await waitFor(() =>
      expect(window.location.pathname).toBe("/admin/integrations/12")
    );
  });

  test("re-picking the preselected sign-in closes the list", async () => {
    mockProbe.mockResolvedValue(OAUTH_PROBE);
    const { user } = open({ kind: "mcp_server" });
    await fillConnect(
      user,
      "Docs",
      add.mcp.url.title,
      "https://mcp.example.com/mcp"
    );
    await screen.findByText(add.mcp.probe.oauth);

    const mode = screen.getByRole("combobox", { name: copy.signIn.mode.title });
    await user.click(mode);
    await user.click(
      await screen.findByRole("option", { name: copy.signIn.mode.individual })
    );

    // An open list covers the Advanced toggle below it.
    await waitFor(() =>
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
    );
    expect(mode).toHaveValue(copy.signIn.mode.individual);
  });

  test("a group-scoped manager cannot pick Onyx login", async () => {
    mockGlobalHolder = false;
    mockProbe.mockResolvedValue(OAUTH_PROBE);
    const { user } = open({ kind: "mcp_server" });
    await fillConnect(
      user,
      "Docs",
      add.mcp.url.title,
      "https://mcp.example.com/mcp"
    );
    await screen.findByText(add.mcp.probe.oauth);

    await user.click(
      screen.getByRole("button", { name: `Expand ${add.advanced}` })
    );
    await user.click(
      screen.getByRole("combobox", { name: copy.signIn.method.title })
    );
    expect(
      await screen.findByRole("option", { name: copy.signIn.method.oauth2 })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: copy.signIn.method.onyxLogin })
    ).not.toBeInTheDocument();
  });

  test("Continue checks an unreachable server again after Back", async () => {
    mockProbe
      .mockResolvedValueOnce({
        kind: "unreachable",
        reason: "connection_failed",
      })
      .mockResolvedValueOnce(OAUTH_PROBE);
    const { user } = open({ kind: "mcp_server" });
    await fillConnect(
      user,
      "Docs",
      add.mcp.url.title,
      "https://mcp.example.com/mcp"
    );
    await screen.findByText(add.mcp.probe.unreachable);

    await user.click(screen.getByRole("button", { name: add.back }));
    await user.click(screen.getByRole("button", { name: add.continue }));

    expect(await screen.findByText(add.mcp.probe.oauth)).toBeInTheDocument();
    expect(mockProbe).toHaveBeenCalledTimes(2);
  });

  test("a server with no detected transport does not keep the last one", async () => {
    mockProbe.mockResolvedValueOnce(OAUTH_PROBE).mockResolvedValueOnce({
      kind: "unreachable",
      reason: "connection_failed",
    });
    const fetchMock = mockFetch({
      "POST /api/admin/integrations": makeDetail({ id: 12 }),
      "/api/admin/integrations": [],
    });
    const { user } = open({ kind: "mcp_server" });
    await fillConnect(
      user,
      "Docs",
      add.mcp.url.title,
      "https://mcp.example.com/sse"
    );
    await screen.findByText(add.mcp.probe.oauth);
    await user.click(screen.getByRole("button", { name: add.back }));
    const url = screen.getByRole("textbox", { name: add.mcp.url.title });
    await user.clear(url);
    await user.type(url, "https://other.example.com/mcp");
    await user.click(screen.getByRole("button", { name: add.continue }));
    await screen.findByText(add.mcp.probe.unreachable);
    await submit(user);

    await waitFor(() =>
      expect(
        requestBody(fetchMock, "POST", "/api/admin/integrations")
      ).toMatchObject({
        config: {
          server_url: "https://other.example.com/mcp",
          transport: "STREAMABLE_HTTP",
        },
      })
    );
  });

  test("a prefilled server keeps its transport when the check finds none", async () => {
    mockProbe.mockResolvedValue({
      kind: "unreachable",
      reason: "connection_failed",
    });
    const fetchMock = mockFetch({
      "POST /api/admin/integrations": makeDetail({ id: 12 }),
      "/api/admin/integrations": [],
      "/api/integrations": [],
    });
    const { user } = open({
      kind: "prefill",
      prefill: {
        name: "Docs",
        serverUrl: "https://MCP.example.com/sse",
        transport: "SSE",
        returnTo: "/app/customize/plugins/7?tab=integrations",
      },
    });
    await screen.findByText(add.mcp.probe.unreachable);
    await submit(user);

    await waitFor(() =>
      expect(
        requestBody(fetchMock, "POST", "/api/admin/integrations")
      ).toMatchObject({ config: { transport: "SSE" } })
    );
  });

  test("Back to rename keeps the sign-in and transport", async () => {
    mockProbe.mockResolvedValue(OAUTH_PROBE);
    const fetchMock = mockFetch({
      "POST /api/admin/integrations": makeDetail({ id: 12 }),
      "/api/admin/integrations": [],
    });
    const { user } = open({ kind: "mcp_server" });
    await fillConnect(
      user,
      "Docs",
      add.mcp.url.title,
      "https://mcp.example.com/sse"
    );
    await screen.findByText(add.mcp.probe.oauth);
    await user.click(
      screen.getByRole("combobox", { name: copy.signIn.mode.title })
    );
    await user.click(
      await screen.findByRole("option", { name: copy.signIn.mode.none })
    );
    await user.click(
      screen.getByRole("button", { name: `Expand ${add.advanced}` })
    );
    await user.click(
      screen.getByRole("combobox", { name: add.mcp.transport.title })
    );
    await user.click(
      await screen.findByRole("option", {
        name: add.mcp.transport.streamableHttp,
      })
    );

    await user.click(screen.getByRole("button", { name: add.back }));
    await user.type(
      screen.getByRole("textbox", { name: add.name.title }),
      " Server"
    );
    await user.click(screen.getByRole("button", { name: add.continue }));
    await submit(user);

    await waitFor(() =>
      expect(
        requestBody(fetchMock, "POST", "/api/admin/integrations")
      ).toMatchObject({
        name: "Docs Server",
        auth_mode: "none",
        config: { transport: "STREAMABLE_HTTP" },
      })
    );
    expect(mockProbe).toHaveBeenCalledTimes(1);
  });

  test("asks for a name and a URL before the check", async () => {
    const { user } = open({ kind: "mcp_server" });
    await user.click(screen.getByRole("button", { name: add.continue }));
    expect(screen.getByText(add.name.required)).toBeInTheDocument();
    expect(screen.getByText(add.mcp.url.error)).toBeInTheDocument();
    expect(mockProbe).not.toHaveBeenCalled();
  });

  test("hides the owner without global manage:actions", async () => {
    mockGlobalHolder = false;
    mockProbe.mockResolvedValue({
      kind: "public",
      transport: "STREAMABLE_HTTP",
      tool_count: 2,
      server_name: "Docs",
    });
    const { user } = open({ kind: "mcp_server" });
    await fillConnect(
      user,
      "Docs",
      add.mcp.url.title,
      "https://docs.example.com/mcp"
    );
    await screen.findByText("Found 2 tools. The server needs no sign-in.");
    await user.click(
      screen.getByRole("button", { name: `Expand ${add.advanced}` })
    );
    expect(
      screen.getByRole("combobox", { name: add.mcp.transport.title })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: add.owner.title })
    ).not.toBeInTheDocument();
  });

  test("a deep link with a bad URL shows the URL error and checks nothing", async () => {
    open({
      kind: "prefill",
      prefill: {
        name: "Linear",
        serverUrl: "not a url",
        transport: "STREAMABLE_HTTP",
        returnTo: "/app/customize/plugins/7?tab=integrations",
      },
    });
    expect(await screen.findByText(add.mcp.url.error)).toBeInTheDocument();
    expect(mockProbe).not.toHaveBeenCalled();
  });

  test("a deep link checks the server at once and returns to the plugin", async () => {
    mockProbe.mockResolvedValue(OAUTH_PROBE);
    mockFetch({
      "POST /api/admin/integrations": makeDetail({ id: 12 }),
      "/api/admin/integrations": [],
      "/api/integrations": [],
    });
    const { user } = open({
      kind: "prefill",
      prefill: {
        name: "Linear",
        serverUrl: "https://mcp.linear.app/mcp",
        transport: "STREAMABLE_HTTP",
        returnTo: "/app/customize/plugins/7?tab=integrations",
      },
    });
    expect(await screen.findByText(add.mcp.probe.oauth)).toBeInTheDocument();
    expect(mockProbe.mock.calls[0]?.[0]).toBe("https://mcp.linear.app/mcp");
    await submit(user);
    await waitFor(() =>
      expect(window.location.pathname + window.location.search).toBe(
        "/app/customize/plugins/7?tab=integrations"
      )
    );
  });
});

// ── Catalog ──────────────────────────────────────────────────────────────────

describe("Catalog", () => {
  test("a preset tile opens its sign-in with the organization fields", async () => {
    const fetchMock = mockFetch({
      "/api/admin/integrations/presets": [GITHUB_PRESET],
      "POST /api/admin/integrations": makeDetail({ id: 12 }),
      "/api/admin/integrations": [],
    });
    const { user } = open({ kind: "catalog" });
    await user.click(await screen.findByRole("button", { name: "GitHub" }));

    await user.type(
      screen.getByRole("textbox", { name: "GitHub organization" }),
      "onyx"
    );
    await submit(user);

    await waitFor(() =>
      expect(
        requestBody(fetchMock, "POST", "/api/admin/integrations")
      ).toMatchObject({
        name: "GitHub",
        auth_mode: "individual",
        auth_method: "oauth2",
        oauth_client: { provider_mode: "preset" },
        config: {
          shape: "preset",
          preset_id: "github",
          organization_credentials: { org: "onyx" },
        },
      })
    );
  });

  test("leaves out a preset that is already added", async () => {
    mockFetch({
      "/api/admin/integrations/presets": [
        GITHUB_PRESET,
        { ...GITHUB_PRESET, id: "zendesk", name: "Zendesk" },
      ],
      "/api/admin/integrations": [
        makeIntegration({ shape: "preset", preset_id: "github" }),
      ],
    });
    open({ kind: "catalog" });

    expect(
      await screen.findByRole("button", { name: "Zendesk" })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "GitHub" })
    ).not.toBeInTheDocument();
  });

  test("a different tile resets the owner; the same tile keeps it", async () => {
    mockProbe.mockResolvedValue(OAUTH_PROBE);
    mockFetch({
      "/api/admin/integrations": [],
      "/api/admin/integrations/presets": [
        GITHUB_PRESET,
        { ...GITHUB_PRESET, id: "LINEAR", name: "Linear" },
      ],
    });
    const { user } = open({ kind: "catalog" });
    const owner = () => screen.getByRole("combobox", { name: add.owner.title });
    await user.click(await screen.findByRole("button", { name: "GitHub" }));
    await user.click(
      screen.getByRole("button", { name: `Expand ${add.advanced}` })
    );
    await user.click(owner());
    await user.click(
      await screen.findByRole("option", { name: add.owner.organization })
    );
    expect(
      screen.getByText(add.owner.organizationDescription)
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: add.back }));
    await user.click(await screen.findByRole("button", { name: "GitHub" }));
    expect(
      screen.getByText(add.owner.organizationDescription)
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: add.back }));
    await user.click(await screen.findByRole("button", { name: "Linear" }));
    await screen.findByText(add.mcp.probe.oauth);
    expect(screen.getByText(add.owner.personalDescription)).toBeInTheDocument();
  });

  test("a tile left while detecting does not reuse another tile's setup", async () => {
    mockProbe.mockReturnValue(new Promise(() => undefined));
    mockFetch({
      "/api/admin/integrations/presets": [GITHUB_PRESET],
      "/api/admin/integrations": [],
    });
    const { user } = open({ kind: "catalog" });
    await user.click(await screen.findByRole("button", { name: "GitHub" }));
    await user.click(screen.getByRole("button", { name: add.back }));
    await user.click(await screen.findByRole("button", { name: "Notion" }));
    await user.click(screen.getByRole("button", { name: add.back }));

    await user.click(await screen.findByRole("button", { name: "Notion" }));

    expect(mockProbe).toHaveBeenCalledTimes(2);
    expect(
      screen.queryByRole("textbox", { name: /GitHub organization/ })
    ).not.toBeInTheDocument();
  });

  test("the same tile again checks a server that was unreachable", async () => {
    mockProbe
      .mockResolvedValueOnce({
        kind: "unreachable",
        reason: "connection_failed",
      })
      .mockResolvedValueOnce(OAUTH_PROBE);
    mockFetch({
      "/api/admin/integrations/presets": [],
      "/api/admin/integrations": [],
    });
    const { user } = open({ kind: "catalog" });
    await user.click(await screen.findByRole("button", { name: "Notion" }));
    await waitFor(() => expect(mockProbe).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("button", { name: add.back }));

    await user.click(await screen.findByRole("button", { name: "Notion" }));

    expect(await screen.findByText(add.mcp.probe.oauth)).toBeInTheDocument();
    expect(mockProbe).toHaveBeenCalledTimes(2);
  });

  test("the same tile again keeps the entered credentials", async () => {
    mockFetch({
      "/api/admin/integrations/presets": [GITHUB_PRESET],
      "/api/admin/integrations": [],
    });
    const { user } = open({ kind: "catalog" });
    await user.click(await screen.findByRole("button", { name: "GitHub" }));
    await user.type(
      screen.getByRole("textbox", { name: /GitHub organization/ }),
      "acme-dev"
    );

    await user.click(screen.getByRole("button", { name: add.back }));
    await user.click(await screen.findByRole("button", { name: "GitHub" }));

    expect(
      screen.getByRole("textbox", { name: /GitHub organization/ })
    ).toHaveValue("acme-dev");
  });

  test("a preset shows its setup steps, callback URL and scopes beside the fields", async () => {
    mockFetch({
      "/api/admin/integrations/presets": [GITHUB_PRESET],
      "/api/admin/integrations": [],
    });
    const { user } = open({ kind: "catalog" });
    const tile = await screen.findByRole("button", { name: "GitHub" });
    expect(tile).toHaveTextContent(copy.shape.preset);
    await user.click(tile);

    expect(
      screen.getByRole("dialog", { name: /^Add GitHub/ })
    ).not.toHaveAccessibleDescription();

    expect(
      screen.getByRole("heading", {
        name: add.setup.title.replace("{name}", "GitHub"),
      })
    ).toBeInTheDocument();
    const steps = screen.getAllByRole("listitem");
    expect(steps.map((step) => step.textContent)).toEqual(
      GITHUB_PRESET.setup_steps
    );
    expect(
      screen.getByText("https://onyx.example.com/craft/v1/apps/oauth/callback")
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: add.setup.copyCallbackUrl })
    ).toBeInTheDocument();
    expect(screen.getByText("repo")).toBeInTheDocument();
    expect(screen.getByText("read:org")).toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: add.setup.open.replace("{name}", "GitHub"),
      })
    ).toHaveAttribute("href", "https://github.com/settings/developers");
  });

  test("a preset with one method hides the method and scopes in Advanced", async () => {
    mockFetch({
      "/api/admin/integrations/presets": [GITHUB_PRESET],
      "/api/admin/integrations": [],
    });
    const { user } = open({ kind: "catalog" });
    await user.click(await screen.findByRole("button", { name: "GitHub" }));
    await user.click(
      screen.getByRole("button", { name: `Expand ${add.advanced}` })
    );

    expect(
      await screen.findByRole("combobox", { name: add.owner.title })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: copy.signIn.method.title })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: copy.signIn.oauth.scopes.title })
    ).not.toBeInTheDocument();
  });

  test("offers only no sign-in for a preset with no sign-in method", async () => {
    mockFetch({
      "/api/admin/integrations": [],
      "/api/admin/integrations/presets": [
        {
          id: "public",
          name: "Public data",
          auth_methods: [null],
          required_org_credential_fields: [],
          setup_steps: [],
          setup_url: null,
          callback_url: null,
          scopes: [],
        },
      ],
    });
    const { user } = open({ kind: "catalog" });
    await user.click(
      await screen.findByRole("button", { name: "Public data" })
    );
    await user.click(
      screen.getByRole("combobox", { name: copy.signIn.mode.title })
    );
    expect(
      (await screen.findAllByRole("option")).map((option) => option.textContent)
    ).toEqual([copy.signIn.mode.none]);
  });

  test("a failed integrations list withholds the presets and keeps suggested servers", async () => {
    mockFetch({
      "/api/admin/integrations/presets": [
        { ...GITHUB_PRESET, id: "zendesk", name: "Zendesk" },
      ],
      "/api/admin/integrations": () => new Response(null, { status: 500 }),
    });
    open({ kind: "catalog" });

    expect(await screen.findByText(add.preset.loadFailed)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Atlassian" })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Zendesk" })
    ).not.toBeInTheDocument();
  });

  test("one grid by name, with a hosted MCP server in place of its preset", async () => {
    mockFetch({
      "/api/admin/integrations": [],
      "/api/admin/integrations/presets": [
        GITHUB_PRESET,
        { ...GITHUB_PRESET, id: "LINEAR", name: "Linear" },
        { ...GITHUB_PRESET, id: "NOTION", name: "Notion" },
      ],
    });
    open({ kind: "catalog" });
    await screen.findByRole("button", { name: "GitHub" });

    expect(
      screen
        .getAllByRole("button")
        .map((button) => button.getAttribute("aria-label"))
        .filter((label) =>
          ["Atlassian", "GitHub", "Linear", "Notion", "Sentry"].includes(
            label ?? ""
          )
        )
    ).toEqual(["Atlassian", "GitHub", "Linear", "Notion", "Sentry"]);
  });

  test("a suggested server tile checks the server with its name filled", async () => {
    mockProbe.mockResolvedValue(OAUTH_PROBE);
    mockFetch({
      "/api/admin/integrations": [],
      "/api/admin/integrations/presets": [
        { ...GITHUB_PRESET, id: "LINEAR", name: "Linear" },
      ],
    });
    const { user } = open({ kind: "catalog" });
    const tile = await screen.findByRole("button", { name: "Linear" });
    expect(tile).toHaveTextContent(copy.shape.mcp_server);
    await user.click(tile);
    expect(await screen.findByText(add.mcp.probe.oauth)).toBeInTheDocument();
    expect(mockProbe.mock.calls[0]?.[0]).toBe("https://mcp.linear.app/mcp");
    expect(
      screen.getByRole("dialog", { name: /^Add Linear/ })
    ).not.toHaveAccessibleDescription();
    await user.click(screen.getByRole("button", { name: add.back }));
    expect(
      await screen.findByRole("button", { name: "Linear" })
    ).toBeInTheDocument();
  });
});

// ── Custom API ───────────────────────────────────────────────────────────────

describe("Custom API", () => {
  test("a spec URL imports the spec and resolves a relative server", async () => {
    const fetchMock = mockFetch({
      "POST /api/admin/integrations/openapi-import": {
        shape: "openapi",
        openapi_document: "{}",
        base_url: "/api/v3",
        endpoints: ["GET /pets List pets", "POST /pets Add a pet"],
        skipped: [],
      },
      "POST /api/admin/integrations": makeDetail({ id: 13 }),
      "/api/admin/integrations": [],
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Pets",
      add.api.url.title,
      "https://pets.example.com/api/v3/openapi.json"
    );
    expect(
      await screen.findByText("REST API, 2 endpoints")
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: add.rest.endpoints.title })
    ).not.toBeInTheDocument();
    await submit(user);

    await waitFor(() =>
      expect(
        requestBody(fetchMock, "POST", "/api/admin/integrations")
      ).toMatchObject({
        name: "Pets",
        auth_mode: "none",
        auth_method: null,
        config: {
          shape: "openapi",
          openapi_document: "{}",
          base_url: "https://pets.example.com/api/v3",
          endpoints: ["GET /pets List pets", "POST /pets Add a pet"],
        },
      })
    );
  });

  test("lists the endpoints that the import skipped", async () => {
    const skipped =
      "POST /pets/{petId}/photo: the body is application/octet-stream, and only application/json is supported";
    mockFetch({
      "POST /api/admin/integrations/openapi-import": {
        shape: "openapi",
        openapi_document: "{}",
        base_url: "https://pets.example.com",
        endpoints: ["GET /pets List pets"],
        skipped: [skipped],
      },
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Pets",
      add.api.url.title,
      "https://pets.example.com/openapi.json"
    );

    expect(
      await screen.findByText("REST API, 1 endpoint. 1 skipped.")
    ).toBeInTheDocument();
    expect(screen.queryByText(skipped)).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", {
        name: `Expand ${add.detected.skippedTitle}`,
      })
    );
    expect(await screen.findByText(skipped)).toBeInTheDocument();
  });

  test("a spec with no actions stops at the connect step", async () => {
    const skipped =
      "POST /pets/{petId}/photo: the body is application/octet-stream, and only application/json is supported";
    mockFetch({
      "POST /api/admin/integrations/openapi-import": {
        shape: "openapi",
        openapi_document: "{}",
        base_url: "https://pets.example.com",
        endpoints: [],
        skipped: [skipped],
      },
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Pets",
      add.api.url.title,
      "https://pets.example.com/openapi.json"
    );

    expect(await screen.findByText(add.api.noActions)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Add$/ })
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: add.continue })
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", {
        name: `Expand ${add.detected.skippedTitle}`,
      })
    );
    expect(await screen.findByText(skipped)).toBeInTheDocument();
  });

  test.each([
    ["no server", "", "https://pets.example.com/api/v2/"],
    ["a relative server", "/", "https://pets.example.com/api/v2"],
    [
      "an absolute server",
      "https://prod.example.com",
      "https://pets.example.com/api/v2",
    ],
  ])(
    "an uploaded spec with %s takes the URL as its base URL",
    async (_case, specBaseUrl, url) => {
      const fetchMock = mockFetch({
        "POST /api/admin/integrations/openapi-import": {
          shape: "openapi",
          openapi_document: "{}",
          base_url: specBaseUrl,
          endpoints: ["GET /pets List pets"],
          skipped: [],
        },
        "POST /api/admin/integrations": makeDetail({ id: 15 }),
        "/api/admin/integrations": [],
      });
      const { user } = open({ kind: "api" });
      // jsdom's File has no text().
      const spec = Object.assign(
        new File(["{}"], "openapi.json", { type: "application/json" }),
        { text: async () => "{}" }
      );
      await user.upload(screen.getByLabelText(add.api.upload.label), spec);
      await screen.findByText(
        add.api.upload.chosen.replace("{file}", "openapi.json")
      );
      await fillConnect(user, "Pets", add.api.url.title, url);
      const baseUrl = await screen.findByRole("textbox", {
        name: add.rest.baseUrl.title,
      });
      expect(baseUrl).toHaveValue("https://pets.example.com/api/v2");
      await submit(user);

      await waitFor(() =>
        expect(
          requestBody(fetchMock, "POST", "/api/admin/integrations")
        ).toMatchObject({
          config: {
            shape: "openapi",
            base_url: "https://pets.example.com/api/v2",
          },
        })
      );
    }
  );

  test("Back to rename keeps an edited base URL", async () => {
    const fetchMock = mockFetch({
      "POST /api/admin/integrations/openapi-import": {
        shape: "openapi",
        openapi_document: "{}",
        base_url: "",
        endpoints: ["GET /pets List pets"],
        skipped: [],
      },
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Pets",
      add.api.url.title,
      "https://pets.example.com/specs/openapi.json"
    );
    const baseUrl = await screen.findByRole("textbox", {
      name: add.rest.baseUrl.title,
    });
    await user.clear(baseUrl);
    await user.type(baseUrl, "https://staging.pets.example.com");

    await user.click(screen.getByRole("button", { name: add.back }));
    await user.type(
      screen.getByRole("textbox", { name: add.name.title }),
      " API"
    );
    await user.click(screen.getByRole("button", { name: add.continue }));

    expect(
      await screen.findByRole("textbox", { name: add.rest.baseUrl.title })
    ).toHaveValue("https://staging.pets.example.com");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test("Back to a bad URL after an uploaded spec shows the URL error", async () => {
    const fetchMock = mockFetch({
      "POST /api/admin/integrations/openapi-import": {
        shape: "openapi",
        openapi_document: "{}",
        base_url: "https://prod.example.com",
        endpoints: ["GET /pets List pets"],
        skipped: [],
      },
    });
    const { user } = open({ kind: "api" });
    // jsdom's File has no text().
    const spec = Object.assign(
      new File(["{}"], "openapi.json", { type: "application/json" }),
      { text: async () => "{}" }
    );
    await user.upload(screen.getByLabelText(add.api.upload.label), spec);
    await screen.findByText(
      add.api.upload.chosen.replace("{file}", "openapi.json")
    );
    await user.type(
      screen.getByRole("textbox", { name: add.name.title }),
      "Pets"
    );
    await user.click(screen.getByRole("button", { name: add.continue }));
    await screen.findByRole("button", { name: /^Add$/ });

    await user.click(screen.getByRole("button", { name: add.back }));
    await user.type(
      screen.getByRole("textbox", { name: add.api.url.title }),
      "api.example.com/v2"
    );
    await user.click(screen.getByRole("button", { name: add.continue }));

    expect(screen.getByText(add.api.url.error)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Add$/ })
    ).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test("a spec with several servers asks which base URL to call", async () => {
    const fetchMock = mockFetch({
      "POST /api/admin/integrations/openapi-import": {
        shape: "openapi",
        openapi_document: "{}",
        base_url: "",
        endpoints: ["GET /pets List pets"],
        skipped: [],
      },
      "POST /api/admin/integrations": makeDetail({ id: 16 }),
      "/api/admin/integrations": [],
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Pets",
      add.api.url.title,
      "https://pets.example.com/specs/openapi.json"
    );
    const baseUrl = await screen.findByRole("textbox", {
      name: add.rest.baseUrl.title,
    });
    expect(baseUrl).toHaveValue("https://pets.example.com");
    await user.clear(baseUrl);
    await submit(user);
    expect(
      await screen.findByText(add.rest.baseUrl.required)
    ).toBeInTheDocument();
    await user.type(baseUrl, "https://staging.pets.example.com/v1/");
    await submit(user);

    await waitFor(() =>
      expect(
        requestBody(fetchMock, "POST", "/api/admin/integrations")
      ).toMatchObject({
        config: {
          shape: "openapi",
          base_url: "https://staging.pets.example.com/v1",
        },
      })
    );
  });

  test("a server variable with no default asks for the base URL", async () => {
    mockFetch({
      "POST /api/admin/integrations/openapi-import": {
        shape: "openapi",
        openapi_document: "{}",
        base_url: "https://api.example.com/{version}",
        endpoints: ["GET /pets List pets"],
        skipped: [],
      },
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Pets",
      add.api.url.title,
      "https://api.example.com/openapi.json"
    );
    expect(
      await screen.findByRole("textbox", { name: add.rest.baseUrl.title })
    ).toHaveValue("https://api.example.com/{version}");
  });

  test("a server that is not http(s) asks for the base URL", async () => {
    mockFetch({
      "POST /api/admin/integrations/openapi-import": {
        shape: "openapi",
        openapi_document: "{}",
        base_url: "ftp://files.example.com/api",
        endpoints: ["GET /pets List pets"],
        skipped: [],
      },
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Pets",
      add.api.url.title,
      "https://api.example.com/openapi.json"
    );
    expect(
      await screen.findByRole("textbox", { name: add.rest.baseUrl.title })
    ).toHaveValue("ftp://files.example.com/api");
    await submit(user);
    expect(
      await screen.findByText(add.rest.baseUrl.required)
    ).toBeInTheDocument();
  });

  test("a spec that Onyx cannot add shows its error at the URL", async () => {
    const fetchMock = mockFetch({
      "POST /api/admin/integrations/openapi-import": () =>
        new Response(
          JSON.stringify({
            error_code: "VALIDATION_ERROR",
            detail: "No methods found in OpenAPI schema",
          }),
          { status: 400 }
        ),
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Pets",
      add.api.url.title,
      "https://pets.example.com/openapi.json"
    );

    expect(
      await screen.findByText(
        "The spec cannot be added: No methods found in OpenAPI schema"
      )
    ).toBeInTheDocument();
    // A spec that fails is not a GraphQL endpoint or a REST base URL.
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // A new URL clears the error.
    await user.type(
      screen.getByRole("textbox", { name: add.api.url.title }),
      "x"
    );
    expect(
      screen.queryByText(
        "The spec cannot be added: No methods found in OpenAPI schema"
      )
    ).not.toBeInTheDocument();
  });

  test("a URL with no spec and no GraphQL is a REST base URL", async () => {
    const fetchMock = mockFetch({
      "POST /api/admin/integrations/openapi-import": () => failure(400),
      "POST /api/admin/integrations/graphql-introspect": () => failure(400),
      "POST /api/admin/integrations": makeDetail({ id: 14 }),
      "/api/admin/integrations": [],
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Billing",
      add.api.url.title,
      // No path: the base URL must not end in "/".
      "https://billing.example.com"
    );
    expect(await screen.findByText(add.detected.rest)).toBeInTheDocument();
    await submit(user);
    expect(
      await screen.findByText(add.rest.endpoints.required)
    ).toBeInTheDocument();
    await user.type(
      screen.getByRole("textbox", { name: add.rest.endpoints.title }),
      "GET /invoices?status List invoices{enter}POST /invoices Create an invoice"
    );
    await submit(user);

    await waitFor(() =>
      expect(requestBody(fetchMock, "POST", "/api/admin/integrations")).toEqual(
        {
          for_organization: false,
          name: "Billing",
          description: null,
          auth_mode: "none",
          auth_method: null,
          header_template: null,
          oauth_client: null,
          config: {
            shape: "openapi",
            openapi_document: null,
            base_url: "https://billing.example.com",
            endpoints: [
              "GET /invoices?status List invoices",
              "POST /invoices Create an invoice",
            ],
          },
        }
      )
    );
  });

  test("a URL that Onyx cannot reach is a REST base URL with a warning", async () => {
    const detail =
      "The URL is blocked. An admin can allow it in SSRF Protection.";
    const fetchMock = mockFetch({
      "POST /api/admin/integrations/openapi-import": () =>
        new Response(JSON.stringify({ error_code: "BAD_GATEWAY", detail }), {
          status: 502,
        }),
      "POST /api/admin/integrations": makeDetail({ id: 15 }),
      "/api/admin/integrations": [],
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Billing",
      add.api.url.title,
      "https://billing.internal/"
    );

    expect(
      await screen.findByText(
        add.detected.restUnreachable.replace("{detail}", detail)
      )
    ).toBeInTheDocument();
    // An unreachable URL is not checked for GraphQL.
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await user.type(
      screen.getByRole("textbox", { name: add.rest.endpoints.title }),
      "GET /invoices List invoices"
    );
    await submit(user);
    await waitFor(() =>
      expect(
        requestBody(fetchMock, "POST", "/api/admin/integrations")
      ).toMatchObject({
        config: {
          shape: "openapi",
          openapi_document: null,
          base_url: "https://billing.internal",
          endpoints: ["GET /invoices List invoices"],
        },
      })
    );
  });

  test("Continue checks an unreachable URL again after Back", async () => {
    const detail = "The URL timed out.";
    let reachable = false;
    const fetchMock = mockFetch({
      "POST /api/admin/integrations/openapi-import": () =>
        reachable
          ? failure(400)
          : new Response(
              JSON.stringify({ error_code: "BAD_GATEWAY", detail }),
              { status: 502 }
            ),
      "POST /api/admin/integrations/graphql-introspect": {
        shape: "graphql",
        endpoint_url: "https://billing.example.com/graphql",
        graphql_schema: "type Query { invoices: Int }",
      },
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Billing",
      add.api.url.title,
      "https://billing.example.com/graphql"
    );
    await screen.findByText(
      add.detected.restUnreachable.replace("{detail}", detail)
    );

    reachable = true;
    await user.click(screen.getByRole("button", { name: add.back }));
    await user.click(screen.getByRole("button", { name: add.continue }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(
      screen.queryByText(
        add.detected.restUnreachable.replace("{detail}", detail)
      )
    ).not.toBeInTheDocument();
  });

  test("Back to rename after a warning keeps the endpoints", async () => {
    const detail = "The URL timed out.";
    const fetchMock = mockFetch({
      "POST /api/admin/integrations/openapi-import": () =>
        new Response(JSON.stringify({ error_code: "BAD_GATEWAY", detail }), {
          status: 502,
        }),
      "POST /api/admin/integrations": makeDetail({ id: 15 }),
      "/api/admin/integrations": [],
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Billing",
      add.api.url.title,
      "https://billing.internal/"
    );
    await user.type(
      await screen.findByRole("textbox", { name: add.rest.endpoints.title }),
      "GET /invoices List invoices"
    );

    await user.click(screen.getByRole("button", { name: add.back }));
    await user.type(
      screen.getByRole("textbox", { name: add.name.title }),
      " API"
    );
    await user.click(screen.getByRole("button", { name: add.continue }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(
      await screen.findByRole("textbox", { name: add.rest.endpoints.title })
    ).toHaveValue("GET /invoices List invoices");
  });

  test("a URL whose answer is over the spec size limit warns and is a REST base URL", async () => {
    const detail = "The spec is larger than 5 MB.";
    const fetchMock = mockFetch({
      "POST /api/admin/integrations/openapi-import": () =>
        new Response(
          JSON.stringify({ error_code: "PAYLOAD_TOO_LARGE", detail }),
          { status: 413 }
        ),
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Billing",
      add.api.url.title,
      "https://billing.example.com/"
    );

    expect(
      await screen.findByText(
        add.detected.restTooLarge.replace("{detail}", detail)
      )
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("textbox", { name: add.rest.endpoints.title })
    ).toBeInTheDocument();
  });

  test("an endpoint that Onyx cannot introspect warns and is a REST base URL", async () => {
    const detail = "The URL did not answer in time.";
    const fetchMock = mockFetch({
      "POST /api/admin/integrations/openapi-import": () => failure(400),
      "POST /api/admin/integrations/graphql-introspect": () =>
        new Response(JSON.stringify({ error_code: "BAD_GATEWAY", detail }), {
          status: 502,
        }),
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Billing",
      add.api.url.title,
      "https://billing.example.com/graphql"
    );

    expect(
      await screen.findByText(
        add.detected.restUnreachable.replace("{detail}", detail)
      )
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  test("a new URL checks again and starts the setup over", async () => {
    const fetchMock = mockFetch({
      "POST /api/admin/integrations/openapi-import": {
        shape: "openapi",
        openapi_document: "{}",
        base_url: "https://pets.example.com",
        endpoints: ["GET /pets List pets"],
        skipped: [],
      },
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Pets",
      add.api.url.title,
      "https://pets.example.com/v1/openapi.json"
    );
    await user.click(
      await screen.findByRole("combobox", { name: copy.signIn.mode.title })
    );
    await user.click(
      await screen.findByRole("option", { name: copy.signIn.mode.individual })
    );

    // The new spec calls the same server, but it is a new detection.
    await user.click(screen.getByRole("button", { name: add.back }));
    const url = screen.getByRole("textbox", { name: add.api.url.title });
    await user.clear(url);
    await user.type(url, "https://pets.example.com/v2/openapi.json");
    await user.click(screen.getByRole("button", { name: add.continue }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(
      await screen.findByRole("combobox", { name: copy.signIn.mode.title })
    ).toHaveValue(copy.signIn.mode.none);
  });

  test("a failed check is an error, not a REST base URL", async () => {
    const fetchMock = mockFetch({
      "POST /api/admin/integrations/openapi-import": () => failure(400),
      "POST /api/admin/integrations/graphql-introspect": () => failure(500),
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Billing",
      add.api.url.title,
      "https://billing.example.com"
    );

    expect(await screen.findByText(add.api.checkFailed)).toBeInTheDocument();
    expect(screen.queryByText(add.detected.rest)).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await user.type(screen.getByLabelText(add.api.url.title), "/v2");
    expect(screen.queryByText(add.api.checkFailed)).not.toBeInTheDocument();
  });

  test("a schema over the size limit shows the size error", async () => {
    const detail = "The schema is larger than 5 MB. Upload a smaller SDL file.";
    const fetchMock = mockFetch({
      "POST /api/admin/integrations/openapi-import": () => failure(400),
      "POST /api/admin/integrations/graphql-introspect": () =>
        new Response(JSON.stringify({ detail }), { status: 413 }),
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Billing",
      add.api.url.title,
      "https://billing.example.com/graphql"
    );

    expect(
      await screen.findByText(add.api.specError.replace("{detail}", detail))
    ).toBeInTheDocument();
    expect(screen.queryByText(add.detected.rest)).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  test("waits for the spec file and shows a read error", async () => {
    let finishRead: (text: string) => void = () => undefined;
    const pending = Object.assign(
      new File(["{}"], "openapi.json", { type: "application/json" }),
      {
        text: () =>
          new Promise<string>((resolve) => {
            finishRead = resolve;
          }),
      }
    );
    const { user } = open({ kind: "api" });
    await user.upload(screen.getByLabelText(add.api.upload.label), pending);
    expect(screen.getByRole("button", { name: add.continue })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: add.api.upload.label })
    ).toBeDisabled();
    finishRead("{}");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: add.continue })).toBeEnabled()
    );

    await user.click(
      screen.getByRole("button", { name: add.api.upload.remove })
    );
    const broken = Object.assign(
      new File(["{}"], "openapi.json", { type: "application/json" }),
      { text: () => Promise.reject(new Error("unreadable")) }
    );
    await user.upload(screen.getByLabelText(add.api.upload.label), broken);
    expect(await screen.findByText(add.api.failed)).toBeInTheDocument();
  });

  test("a blank schema file blocks Continue until discarded", async () => {
    const fetchMock = mockFetch({});
    const { user } = open({ kind: "api" });
    await user.type(
      screen.getByRole("textbox", { name: add.api.url.title }),
      "https://api.example.com/graphql"
    );
    await user.upload(
      screen.getByLabelText(add.api.upload.label),
      Object.assign(new File([" \n"], "schema.graphql"), {
        text: async () => " \n",
      })
    );

    expect(await screen.findByText(add.api.failed)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: add.continue })).toBeDisabled();

    await user.click(
      screen.getByRole("button", { name: add.api.upload.remove })
    );
    expect(screen.queryByText(add.api.failed)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: add.continue })).toBeEnabled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("a spec file over the size limit blocks Continue until discarded", async () => {
    const read = jest.fn(() => Promise.resolve("{}"));
    const big = new File(["{}"], "openapi.json", { type: "application/json" });
    Object.defineProperties(big, {
      size: { value: 5 * 1024 * 1024 + 1 },
      text: { value: read },
    });
    const { user } = open({ kind: "api" });
    await user.type(
      screen.getByRole("textbox", { name: add.api.url.title }),
      "https://api.example.com"
    );
    await user.upload(screen.getByLabelText(add.api.upload.label), big);

    expect(await screen.findByText(add.api.tooLarge)).toBeInTheDocument();
    expect(read).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: add.continue })).toBeDisabled();

    await user.click(
      screen.getByRole("button", { name: add.api.upload.remove })
    );
    expect(screen.queryByText(add.api.tooLarge)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: add.continue })).toBeEnabled();
  });

  test("a GraphQL endpoint counts its queries and mutations", async () => {
    const schema = `"""Root"""
type Query {
  # A brace in a comment, such as }, does not end the type.
  """One ticket"""
  ticket(id: ID!, filter: Filter = {status: "open"}): Ticket
  tickets(first: Int): [Ticket!]!
}
type Mutation { ticketClose(id: ID!): Ticket }
type Ticket { id: ID! title: String! }
extend type Query { closedTickets: [Ticket!]! }`;
    const fetchMock = mockFetch({
      "POST /api/admin/integrations/openapi-import": () => failure(400),
      "POST /api/admin/integrations/graphql-introspect": {
        shape: "graphql",
        endpoint_url: "https://api.example.com/graphql",
        graphql_schema: schema,
      },
      "POST /api/admin/integrations": makeDetail({ id: 15 }),
      "/api/admin/integrations": [],
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Tickets",
      add.api.url.title,
      "https://api.example.com/graphql"
    );
    expect(
      await screen.findByText("GraphQL API, 3 queries and 1 mutation")
    ).toBeInTheDocument();
    await submit(user);
    await waitFor(() =>
      expect(
        requestBody(fetchMock, "POST", "/api/admin/integrations")
      ).toMatchObject({
        config: {
          shape: "graphql",
          endpoint_url: "https://api.example.com/graphql",
          graphql_schema: schema,
        },
      })
    );
  });

  test("a GraphQL schema with deep argument nesting counts at once", async () => {
    const depth = 500_000;
    const schema = `type Query { a${"(".repeat(depth)}${")".repeat(depth)}: Int b: Int }`;
    mockFetch({
      "POST /api/admin/integrations/openapi-import": () => failure(400),
      "POST /api/admin/integrations/graphql-introspect": {
        shape: "graphql",
        endpoint_url: "https://api.example.com/graphql",
        graphql_schema: schema,
      },
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Tickets",
      add.api.url.title,
      "https://api.example.com/graphql"
    );
    expect(
      await screen.findByText("GraphQL API, 2 queries and 0 mutations")
    ).toBeInTheDocument();
  });

  test("a GraphQL schema with a long name and no colon counts at once", async () => {
    const schema = `type Query { a: Int b: Int ${"x".repeat(100_000)} }`;
    mockFetch({
      "POST /api/admin/integrations/openapi-import": () => failure(400),
      "POST /api/admin/integrations/graphql-introspect": {
        shape: "graphql",
        endpoint_url: "https://api.example.com/graphql",
        graphql_schema: schema,
      },
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Tickets",
      add.api.url.title,
      "https://api.example.com/graphql"
    );
    expect(
      await screen.findByText("GraphQL API, 2 queries and 0 mutations")
    ).toBeInTheDocument();
  });

  test("a GraphQL schema with unclosed headers and quotes counts at once", async () => {
    // Each line alone takes seconds with a regex that rescans after a failed
    // match.
    const schema = [
      "type Query { a: Int b: Int }",
      "type Query ".repeat(40_000),
      "schema @".repeat(40_000),
      `"${'\\"'.repeat(100_000)}`,
    ].join("\n");
    mockFetch({
      "POST /api/admin/integrations/openapi-import": () => failure(400),
      "POST /api/admin/integrations/graphql-introspect": {
        shape: "graphql",
        endpoint_url: "https://api.example.com/graphql",
        graphql_schema: schema,
      },
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Tickets",
      add.api.url.title,
      "https://api.example.com/graphql"
    );
    expect(
      await screen.findByText("GraphQL API, 2 queries and 0 mutations")
    ).toBeInTheDocument();
  });

  test("a schema block without a mutation root counts no mutations", async () => {
    mockFetch({
      "POST /api/admin/integrations/openapi-import": () => failure(400),
      "POST /api/admin/integrations/graphql-introspect": {
        shape: "graphql",
        endpoint_url: "https://api.example.com/graphql",
        graphql_schema: `schema { query: Root }
type Root { ticket: Ticket }
type Mutation { ticketClose(id: ID!): Ticket }
type Ticket { id: ID! }`,
      },
    });
    const { user } = open({ kind: "api" });
    await fillConnect(
      user,
      "Tickets",
      add.api.url.title,
      "https://api.example.com/graphql"
    );
    expect(
      await screen.findByText("GraphQL API, 1 query and 0 mutations")
    ).toBeInTheDocument();
  });

  test("asks for a URL or a spec", async () => {
    const fetchMock = mockFetch({});
    const { user } = open({ kind: "api" });
    await user.type(
      screen.getByRole("textbox", { name: add.name.title }),
      "Billing"
    );
    await user.click(screen.getByRole("button", { name: add.continue }));
    expect(screen.getByText(add.api.url.error)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
