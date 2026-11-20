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
} from "@tests/setup/integrationTestUtils";
import { makeAccess } from "@tests/setup/memberIntegrationTestUtils";

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
  installation_policy: "NOT_AVAILABLE",
  access: makeAccess({
    installation_policy: "NOT_AVAILABLE",
    owner_email: "owner@example.com",
    shared_with_everyone: false,
    can_manage: true,
  }),
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

test("shows each integration with its type, sign-in, install setting and status", async () => {
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
  expect(
    row.getByRole("combobox", { name: "Install setting of Linear" })
  ).toHaveValue(messages.skills.installationPolicy.AVAILABLE.label);
  expect(row.getByText(copy.status.ready)).toBeInTheDocument();

  const reportsRow = within(
    within(table).getByText("Reports API").closest("tr") as HTMLElement
  );
  expect(reportsRow.getByText(copy.shape.openapi)).toBeInTheDocument();
  expect(reportsRow.getByText("Organization API key")).toBeInTheDocument();
  expect(
    reportsRow.getByText("Owned by owner@example.com")
  ).toBeInTheDocument();
  expect(
    reportsRow.getByRole("combobox", { name: "Install setting of Reports API" })
  ).toHaveValue(messages.skills.installationPolicy.NOT_AVAILABLE.label);
  expect(reportsRow.getByText(copy.status.needsSetup)).toBeInTheDocument();
});

test("an organization-wide action manager changes the install setting", async () => {
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  const fetchMock = mockList({
    "PUT /api/admin/integrations/1/installation-policy": {
      installation_policy: "REQUIRED",
    },
  });
  render(<IntegrationsPage />);
  await user.click(
    await screen.findByRole("combobox", { name: "Install setting of Linear" })
  );
  await user.click(
    screen.getByRole("option", {
      name: new RegExp(messages.skills.installationPolicy.REQUIRED.label),
    })
  );
  await waitFor(() =>
    expect(
      requestBody(
        fetchMock,
        "PUT",
        "/api/admin/integrations/1/installation-policy"
      )
    ).toEqual({ installation_policy: "REQUIRED" })
  );
});

test("a scoped manager sees the install setting and cannot change it", async () => {
  mockGlobalHolder = false;
  mockScopedManager = true;
  mockList();
  render(<IntegrationsPage />);
  expect(
    await screen.findByRole("combobox", { name: "Install setting of Linear" })
  ).toBeDisabled();
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

  await user.click(screen.getByRole("combobox", { name: copy.filters.label }));
  await user.click(screen.getByRole("option", { name: copy.filters.api }));
  expect(screen.queryByText("Linear")).not.toBeInTheDocument();
  expect(screen.getByText("Reports API")).toBeInTheDocument();

  await user.click(screen.getByRole("combobox", { name: copy.filters.label }));
  await user.click(screen.getByRole("option", { name: copy.filters.mcp }));
  expect(screen.getByText("Linear")).toBeInTheDocument();
  expect(screen.queryByText("Reports API")).not.toBeInTheDocument();

  await user.click(screen.getByRole("combobox", { name: copy.filters.label }));
  await user.click(screen.getByRole("option", { name: copy.filters.all }));
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
