import { render, screen, setupUser, within } from "@tests/setup/test-utils";
import AdminPluginsPage from "@/sections/integrations/AdminPluginsPage";
import messages from "@/i18n/messages/en.json";
import {
  makeIntegration,
  mockFetch,
} from "@/sections/integrations/__tests__/integrationFixtures";

const copy = messages.admin.plugins;

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => window.location.pathname,
}));

const workspace = {
  plugin_id: "plugin-work",
  plugin_name: "Workspace tools",
  scope: "organization" as const,
  owner_email: null,
  installation_policy: "REQUIRED" as const,
};

beforeEach(() => window.history.replaceState(null, "", "/admin/plugins"));
afterEach(() => jest.restoreAllMocks());

test("lists each plugin once with the integrations it holds", async () => {
  mockFetch({
    "/api/admin/integrations": [
      makeIntegration({ id: 1, name: "Linear", plugins: [workspace] }),
      makeIntegration({
        id: 2,
        name: "Sentry",
        plugins: [
          workspace,
          {
            plugin_id: "plugin-mine",
            plugin_name: "My Sentry",
            scope: "personal",
            owner_email: "me@example.com",
            installation_policy: null,
          },
        ],
      }),
      makeIntegration({ id: 3, name: "Loose", plugins: [] }),
    ],
  });
  render(<AdminPluginsPage />);

  const table = await screen.findByRole("table");
  const rows = within(table).getAllByRole("row").slice(1);
  expect(rows).toHaveLength(2);
  const mine = within(rows[0] as HTMLElement);
  expect(mine.getByText("My Sentry")).toBeInTheDocument();
  expect(mine.getByText("My uploads of me@example.com")).toBeInTheDocument();
  const work = within(rows[1] as HTMLElement);
  expect(work.getByText("Workspace tools")).toBeInTheDocument();
  expect(work.getByText(copy.library.organization)).toBeInTheDocument();
  expect(work.getByText("Required")).toBeInTheDocument();
  expect(work.getByRole("button", { name: "Open Linear" })).toBeInTheDocument();
  expect(work.getByRole("button", { name: "Open Sentry" })).toBeInTheDocument();
  expect(screen.queryByText("Loose")).not.toBeInTheDocument();
});

test("opens an integration from its plugin", async () => {
  mockFetch({
    "/api/admin/integrations": [
      makeIntegration({ id: 4, name: "Linear", plugins: [workspace] }),
    ],
  });
  const user = setupUser();
  render(<AdminPluginsPage />);
  await user.click(await screen.findByRole("button", { name: "Open Linear" }));
  expect(window.location.pathname).toBe("/admin/integrations/4");
});

test("shows an empty state with no plugins", async () => {
  mockFetch({ "/api/admin/integrations": [] });
  render(<AdminPluginsPage />);
  expect(await screen.findByText(copy.empty.title)).toBeInTheDocument();
});
