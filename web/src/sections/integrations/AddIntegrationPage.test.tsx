import type { ComponentProps } from "react";
import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { PointerEventsCheckLevel } from "@testing-library/user-event";
import AddIntegrationPage from "@/sections/integrations/AddIntegrationPage";
import type AddOpenAPIActionModal from "@/sections/actions/modals/AddOpenAPIActionModal";
import messages from "@/i18n/messages/en.json";
import {
  makeDetail,
  makeIntegration,
  mockFetch,
  requestBody,
} from "@tests/setup/integrationTestUtils";

const copy = messages.admin.integrations;
type IntegrationType = "mcp_server" | "openapi" | "app";
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
  usePathname: () => "/admin/integrations/new",
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
  installation_policy: "NOT_AVAILABLE",
});

function mockList(extra: Parameters<typeof mockFetch>[0] = {}) {
  return mockFetch({
    "/api/admin/integrations": [linear, reports],
    ...extra,
  });
}

beforeEach(() => {
  window.history.replaceState(null, "", "/admin/integrations/new");
  mockPush.mockClear();
  mockReplace.mockClear();
  mockProbe.mockReset();
  mockGlobalHolder = true;
  mockScopedManager = false;
  mockCraftAvailable = true;
});
afterEach(() => jest.restoreAllMocks());

// ── Add ──────────────────────────────────────────────────────────────────────

async function openAdd(kind: keyof typeof copy.add.type & IntegrationType) {
  // The select menu animates in with pointer-events off.
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(<AddIntegrationPage from="admin" />);
  await user.click(
    screen.getByRole("radio", { name: copy.add.type[kind].title })
  );
  return user;
}

async function startFrom(
  user: ReturnType<typeof setupUser>,
  option: string
): Promise<void> {
  await user.click(
    await screen.findByRole("combobox", { name: copy.add.preset.title })
  );
  await user.click(await screen.findByRole("option", { name: option }));
}

test("offers apps only with Craft", async () => {
  mockCraftAvailable = false;
  mockList();
  render(<AddIntegrationPage from="admin" />);
  expect(
    screen.getByRole("radio", { name: copy.add.type.mcp_server.title })
  ).toBeChecked();
  expect(
    screen.getByRole("radio", { name: copy.add.type.openapi.title })
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("radio", { name: copy.add.type.app.title })
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
  await user.click(
    screen.getByRole("radio", { name: copy.add.type.openapi.title })
  );
  await user.click(
    screen.getByRole("button", { name: copy.add.openapi.schema.add })
  );
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
  const user = await openAdd("app");
  await startFrom(user, "GitHub");
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

test("starts the app over after the type is chosen again", async () => {
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
  const user = await openAdd("app");
  await startFrom(user, "GitHub");
  await user.click(
    screen.getByRole("radio", { name: copy.add.type.mcp_server.title })
  );
  await user.click(
    screen.getByRole("radio", { name: copy.add.type.app.title })
  );
  expect(
    screen.getByRole("combobox", { name: copy.add.preset.title })
  ).toHaveValue(copy.add.preset.custom);
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
  const user = await openAdd("app");
  await startFrom(user, "Public data");
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
  const user = await openAdd("app");
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
