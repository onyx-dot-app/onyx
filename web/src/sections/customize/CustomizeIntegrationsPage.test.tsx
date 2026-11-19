import { render, screen } from "@tests/setup/test-utils";
import { mockFetch } from "@tests/setup/integrationTestUtils";
import {
  makeAccess,
  makeMemberIntegration,
} from "@tests/setup/memberIntegrationTestUtils";
import CustomizeIntegrationsPage from "@/sections/customize/CustomizeIntegrationsPage";

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => window.location.pathname,
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({
    isGlobalHolder: false,
    isScopedManager: false,
  }),
}));

const connected = { state: "connected", reason: null } as const;

afterEach(() => jest.restoreAllMocks());

test("each member row shows its state as Claude does", async () => {
  window.history.replaceState(null, "", "/app/customize/integrations");
  mockFetch({
    "/api/integrations": [
      makeMemberIntegration({
        id: 1,
        name: "Asana",
        status: connected,
        access: makeAccess({ state: "on" }),
      }),
      makeMemberIntegration({
        id: 2,
        name: "Box",
        status: connected,
        access: makeAccess({
          state: "turn_on",
          user_choice: null,
          user_enabled: false,
        }),
      }),
      makeMemberIntegration({ id: 3, name: "Canva" }),
      makeMemberIntegration({
        id: 4,
        name: "Drive",
        access: makeAccess({
          state: "no_access",
          user_enabled: false,
          shared_with_everyone: false,
        }),
      }),
      makeMemberIntegration({
        id: 5,
        name: "Excel",
        status: connected,
        access: makeAccess({ state: "turned_off" }),
      }),
    ],
  });
  render(<CustomizeIntegrationsPage />);

  expect(
    await screen.findByRole("switch", { name: "Use Asana" })
  ).toBeChecked();
  expect(screen.getByRole("switch", { name: "Use Box" })).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Connect Canva" })).toBeVisible();
  expect(
    screen.getByText("No access: this integration is not shared with you.")
  ).toBeVisible();
  expect(screen.getByText("Turned off by an admin.")).toBeVisible();
  expect(
    screen.queryByRole("switch", { name: "Use Drive" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("switch", { name: "Use Excel" })
  ).not.toBeInTheDocument();
});

test("no access rows go below every integration the user can use", async () => {
  window.history.replaceState(null, "", "/app/customize/integrations");
  const noAccess = makeAccess({
    state: "no_access",
    user_enabled: false,
    shared_with_everyone: false,
  });
  mockFetch({
    "/api/integrations": [
      makeMemberIntegration({ id: 1, name: "Asana", access: noAccess }),
      makeMemberIntegration({
        id: 2,
        name: "Zendesk",
        status: connected,
        access: makeAccess({ state: "on" }),
      }),
      makeMemberIntegration({ id: 3, name: "Box", access: noAccess }),
    ],
  });
  render(<CustomizeIntegrationsPage />);

  await screen.findByRole("switch", { name: "Use Zendesk" });
  const names = ["Asana", "Box", "Zendesk"];
  const order = screen
    .getAllByRole("row")
    .map((row) => names.find((name) => row.textContent?.includes(name)))
    .filter((name) => name !== undefined);
  expect(order).toEqual(["Zendesk", "Asana", "Box"]);
});
