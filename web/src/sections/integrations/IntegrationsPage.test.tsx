import type { ComponentProps } from "react";
import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { PointerEventsCheckLevel } from "@testing-library/user-event";
import IntegrationsPage from "@/sections/integrations/IntegrationsPage";
import type AddOpenAPIActionModal from "@/sections/actions/modals/AddOpenAPIActionModal";
import messages from "@/i18n/messages/en.json";
import {
  makeDetail,
  makeIntegration,
  mockFetch,
  requestBody,
} from "@/sections/integrations/__tests__/integrationFixtures";

const copy = messages.admin.integrations;
const mockPush = jest.fn();
const mockReplace = jest.fn();
let mockGlobalHolder = true;
let mockScopedManager = false;
let mockCraftAvailable = true;
const mockProbe = jest.fn();

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
  usePathname: () => "/admin/integrations",
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({
    isGlobalHolder: mockGlobalHolder,
    isScopedManager: mockScopedManager,
  }),
}));
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ onyx_craft_available: mockCraftAvailable }),
}));
jest.mock("@/lib/mcp/svc", () => ({
  streamMCPServerProbe: (...args: unknown[]) => mockProbe(...args),
}));
jest.mock("@/sections/actions/modals/AddOpenAPIActionModal", () => ({
  __esModule: true,
  default: function MockSchemaStep(
    props: ComponentProps<typeof AddOpenAPIActionModal>
  ) {
    return (
      <div role="dialog" aria-label="OpenAPI schema">
        <button
          onClick={() =>
            props.onConfigureAuthentication({
              name: "Reports API",
              description: "Weekly reports",
              definition: { openapi: "3.0.0", info: { title: "Reports API" } },
            })
          }
        >
          Continue
        </button>
      </div>
    );
  },
}));

const linear = makeIntegration();
const reports = makeIntegration({
  id: 2,
  kind: "api",
  shape: "openapi",
  name: "Reports API",
  description: "Weekly reports",
  auth_mode: "shared",
  auth_method: "api_key",
  needs_setup: true,
  setup_reason: "Connect the organization account",
  plugins: [
    {
      plugin_id: "plugin-reports",
      plugin_name: "Reports",
      scope: "personal",
      owner_email: "owner@example.com",
      installation_policy: null,
    },
  ],
});

function mockList(extra: Parameters<typeof mockFetch>[0] = {}) {
  return mockFetch({
    "/api/admin/integrations": [linear, reports],
    ...extra,
  });
}

beforeEach(() => {
  window.history.replaceState(null, "", "/admin/integrations");
  mockPush.mockClear();
  mockReplace.mockClear();
  mockProbe.mockReset();
  mockGlobalHolder = true;
  mockScopedManager = false;
  mockCraftAvailable = true;
});
afterEach(() => jest.restoreAllMocks());

// ── List ─────────────────────────────────────────────────────────────────────

test("shows each integration with its type, sign-in, access and status", async () => {
  mockList();
  render(<IntegrationsPage />);

  const table = await screen.findByRole("table");
  for (const column of Object.values(copy.columns))
    expect(within(table).getByText(column)).toBeInTheDocument();

  const linearRow = within(table).getByText("Linear").closest("tr");
  expect(linearRow).not.toBeNull();
  const row = within(linearRow as HTMLElement);
  expect(row.getByText(copy.shape.mcp_server)).toBeInTheDocument();
  expect(row.getByText("Each user (OAuth)")).toBeInTheDocument();
  expect(row.getByText("Linear (Organization library)")).toBeInTheDocument();
  expect(row.getByText(copy.status.ready)).toBeInTheDocument();

  const reportsRow = within(
    within(table).getByText("Reports API").closest("tr") as HTMLElement
  );
  expect(reportsRow.getByText(copy.shape.openapi)).toBeInTheDocument();
  expect(reportsRow.getByText("Organization API key")).toBeInTheDocument();
  expect(
    reportsRow.getByText("Reports (My uploads of owner@example.com)")
  ).toBeInTheDocument();
  expect(reportsRow.getByText(copy.status.needsSetup)).toBeInTheDocument();
});

test("lists an integration that needs setup first", async () => {
  mockList();
  render(<IntegrationsPage />);
  const table = await screen.findByRole("table");
  const names = within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) => row.textContent ?? "");
  expect(names[0]).toContain("Reports API");
  expect(names[1]).toContain("Linear");
});

test("filters by kind and by search", async () => {
  const user = setupUser();
  mockList();
  render(<IntegrationsPage />);
  await screen.findByText("Linear");

  await user.click(screen.getByRole("button", { name: copy.filters.api }));
  expect(screen.queryByText("Linear")).not.toBeInTheDocument();
  expect(screen.getByText("Reports API")).toBeInTheDocument();

  await user.click(
    screen.getByRole("button", { name: copy.filters.mcp_server })
  );
  expect(screen.getByText("Linear")).toBeInTheDocument();
  expect(screen.queryByText("Reports API")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: copy.filters.all }));
  await user.type(screen.getByRole("searchbox", { name: copy.search }), "week");
  expect(screen.getByText("Reports API")).toBeInTheDocument();
  expect(screen.queryByText("Linear")).not.toBeInTheDocument();

  await user.clear(screen.getByRole("searchbox", { name: copy.search }));
  await user.type(
    screen.getByRole("searchbox", { name: copy.search }),
    "nothing"
  );
  expect(screen.getByText(copy.empty.noResults)).toBeInTheDocument();
});

test("hides Add without manage:actions", async () => {
  mockGlobalHolder = false;
  mockList();
  render(<IntegrationsPage />);
  await screen.findByText("Linear");
  expect(
    screen.queryByRole("button", { name: copy.add.label })
  ).not.toBeInTheDocument();
});

// ── Add ──────────────────────────────────────────────────────────────────────

async function openAdd(kind: keyof typeof copy.shape) {
  // The select menu animates in with pointer-events off.
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(<IntegrationsPage />);
  await screen.findByText("Linear");
  await user.click(screen.getByRole("button", { name: copy.add.label }));
  const dialog = await screen.findByRole("dialog");
  await user.click(
    within(dialog).getByRole("button", { name: copy.shape[kind] })
  );
  return user;
}

test("asks for the kind and offers presets and custom apps only with Craft", async () => {
  const user = setupUser();
  mockCraftAvailable = false;
  mockList();
  render(<IntegrationsPage />);
  await screen.findByText("Linear");
  await user.click(screen.getByRole("button", { name: copy.add.label }));
  const dialog = await screen.findByRole("dialog");
  expect(
    within(dialog).getByRole("button", { name: copy.shape.mcp_server })
  ).toBeInTheDocument();
  expect(
    within(dialog).getByRole("button", { name: copy.shape.openapi })
  ).toBeInTheDocument();
  expect(
    within(dialog).queryByRole("button", { name: copy.shape.preset })
  ).not.toBeInTheDocument();
});

test("does not carry the sign-in of one kind to another kind", async () => {
  mockProbe.mockResolvedValue({
    kind: "oauth",
    transport: "STREAMABLE_HTTP",
    discovery: {
      status: "metadata_found",
      supports_automatic_registration: true,
      supports_client_metadata: null,
      authorization_endpoint: "https://mcp.example.com/authorize",
      token_endpoint: "https://mcp.example.com/token",
    },
  });
  const fetchMock = mockList({
    "POST /api/admin/integrations": makeDetail({ id: 12 }),
  });
  const user = await openAdd("mcp_server");
  await user.type(
    screen.getByRole("textbox", { name: copy.add.mcp.url.title }),
    "https://mcp.example.com/mcp"
  );
  await screen.findByText(copy.add.mcp.probe.oauth, {}, { timeout: 3000 });
  await user.click(screen.getByRole("button", { name: copy.add.back }));
  await user.click(screen.getByRole("button", { name: copy.shape.openapi }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByRole("button", { name: copy.add.submit }));

  await waitFor(() =>
    expect(
      requestBody(fetchMock, "POST", "/api/admin/integrations")
    ).toMatchObject({
      auth_mode: "none",
      auth_method: null,
      oauth_client: null,
    })
  );
});

test("hides the organization choice without global manage:actions", async () => {
  mockGlobalHolder = false;
  mockScopedManager = true;
  mockProbe.mockResolvedValue({
    kind: "public",
    transport: "SSE",
    tool_count: 2,
    server_name: "Docs",
  });
  const fetchMock = mockList({
    "POST /api/admin/integrations": makeDetail({ id: 10 }),
  });
  const user = await openAdd("mcp_server");

  expect(
    screen.queryByRole("combobox", { name: copy.add.owner.title })
  ).not.toBeInTheDocument();
  expect(
    screen.getByText(copy.add.owner.personalDescription)
  ).toBeInTheDocument();
  await user.type(
    screen.getByRole("textbox", { name: copy.add.mcp.url.title }),
    "https://docs.example.com/sse"
  );
  await screen.findByText(
    "Found 2 tools. The server needs no sign-in.",
    {},
    { timeout: 3000 }
  );
  await user.click(screen.getByRole("button", { name: copy.add.submit }));
  await waitFor(() =>
    expect(
      requestBody(fetchMock, "POST", "/api/admin/integrations")
    ).toMatchObject({
      for_organization: false,
      name: "Docs",
      auth_mode: "none",
      auth_method: null,
      config: {
        shape: "mcp_server",
        server_url: "https://docs.example.com/sse",
        transport: "SSE",
      },
    })
  );
});

test("a suggested server fills the name and URL", async () => {
  mockProbe.mockReturnValue(new Promise(() => undefined));
  mockList();
  const user = await openAdd("mcp_server");
  await user.click(screen.getByRole("button", { name: "Linear" }));
  expect(
    screen.getByRole("textbox", { name: copy.add.name.title })
  ).toHaveValue("Linear");
  expect(
    screen.getByRole("textbox", { name: copy.add.mcp.url.title })
  ).toHaveValue("https://mcp.linear.app/mcp");
});

test("shows errors and posts nothing while required fields are empty", async () => {
  const fetchMock = mockList();
  const user = await openAdd("mcp_server");
  await user.click(screen.getByRole("button", { name: copy.add.submit }));
  expect(screen.getByText(copy.add.name.required)).toBeInTheDocument();
  expect(screen.getByText(copy.add.mcp.url.error)).toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    false
  );
});

test("adds an app from a preset with its organization credentials", async () => {
  const fetchMock = mockList({
    "/api/admin/integrations/presets": [
      {
        id: "github",
        name: "GitHub",
        auth_methods: ["oauth2"],
        required_org_credential_fields: [
          { key: "org", label: "GitHub organization", secret: false },
        ],
        setup_instructions: "Create a GitHub OAuth app.",
      },
    ],
    "POST /api/admin/integrations": makeDetail({ id: 12 }),
  });
  const user = await openAdd("preset");

  await user.click(
    await screen.findByRole("combobox", { name: copy.add.preset.placeholder })
  );
  await user.click(await screen.findByRole("option", { name: "GitHub" }));
  expect(screen.getByText("Create a GitHub OAuth app.")).toBeInTheDocument();
  await user.type(
    screen.getByRole("textbox", { name: "GitHub organization" }),
    "onyx"
  );
  await user.click(screen.getByRole("button", { name: copy.add.submit }));

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

test("asks for the preset again after the kind is chosen again", async () => {
  const fetchMock = mockList({
    "/api/admin/integrations/presets": [
      {
        id: "github",
        name: "GitHub",
        auth_methods: ["oauth2"],
        required_org_credential_fields: [],
        setup_instructions: null,
      },
    ],
    "POST /api/admin/integrations": makeDetail({ id: 12 }),
  });
  const user = await openAdd("preset");
  await user.click(
    await screen.findByRole("combobox", { name: copy.add.preset.placeholder })
  );
  await user.click(await screen.findByRole("option", { name: "GitHub" }));
  await user.click(screen.getByRole("button", { name: copy.add.back }));
  await user.click(screen.getByRole("button", { name: copy.shape.preset }));
  await user.click(screen.getByRole("button", { name: copy.add.submit }));

  expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    false
  );
});

test("offers only no sign-in for a preset with no sign-in method", async () => {
  mockList({
    "/api/admin/integrations/presets": [
      {
        id: "public",
        name: "Public data",
        auth_methods: [null],
        required_org_credential_fields: [],
        setup_instructions: null,
      },
    ],
  });
  const user = await openAdd("preset");
  await user.click(
    await screen.findByRole("combobox", { name: copy.add.preset.placeholder })
  );
  await user.click(await screen.findByRole("option", { name: "Public data" }));
  await user.click(
    screen.getByRole("combobox", { name: copy.signIn.mode.title })
  );
  expect(
    (await screen.findAllByRole("option")).map((option) => option.textContent)
  ).toEqual([copy.signIn.mode.none]);
});

test("adds a custom app with URL patterns", async () => {
  const fetchMock = mockList({
    "POST /api/admin/integrations": makeDetail({ id: 13 }),
  });
  const user = await openAdd("custom");
  await user.type(
    screen.getByRole("textbox", { name: copy.add.name.title }),
    "Billing"
  );
  await user.type(
    screen.getByRole("textbox", { name: copy.add.custom.patterns.title }),
    "https://billing.example.com/*{enter}https://api.billing.example.com/*"
  );
  await user.click(screen.getByRole("button", { name: copy.add.submit }));

  await waitFor(() =>
    expect(requestBody(fetchMock, "POST", "/api/admin/integrations")).toEqual({
      for_organization: false,
      name: "Billing",
      description: null,
      auth_mode: "none",
      auth_method: null,
      header_template: null,
      oauth_client: null,
      config: {
        shape: "custom",
        upstream_url_patterns: [
          "https://billing.example.com/*",
          "https://api.billing.example.com/*",
        ],
      },
    })
  );
});
