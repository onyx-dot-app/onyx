import { render, screen, setupUser } from "@tests/setup/test-utils";
import { mockFetch } from "@tests/setup/integrationTestUtils";
import {
  makeMemberAction,
  makeMemberIntegration,
} from "@tests/setup/memberIntegrationTestUtils";
import CustomizeIntegrationPage from "@/sections/customize/CustomizeIntegrationPage";
import messages from "@/i18n/messages/en.json";

const copy = messages.customize.integrationPage;

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => window.location.pathname,
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

afterEach(() => jest.restoreAllMocks());

test("shows the status, Connect and the admin setting of each action", async () => {
  window.history.replaceState(null, "", "/app/customize/integrations/1");
  mockFetch({
    "/api/integrations": [makeMemberIntegration()],
    "/api/action-policies/integration/1": {
      users_can_save_always_allow: false,
      actions: [
        makeMemberAction({
          key: "create_issue",
          display_name: "Create issue",
          effective_admin_policy: "blocked",
        }),
        makeMemberAction({
          key: "list_issues",
          display_name: "List issues",
          effective_admin_policy: "allow",
        }),
        makeMemberAction({
          key: "update_issue",
          display_name: "Update issue",
          effective_admin_policy: "ask",
        }),
      ],
    },
  });
  render(<CustomizeIntegrationPage integrationId={1} />);
  expect(await screen.findByText("Not connected")).toBeVisible();
  expect(screen.getByRole("button", { name: "Connect Linear" })).toBeVisible();

  await setupUser().click(screen.getByRole("tab", { name: copy.tabs.actions }));
  expect(await screen.findByText("Create issue")).toBeVisible();
  expect(screen.getByText("Blocked")).toBeVisible();
  expect(screen.getByText("Allow")).toBeVisible();
  expect(screen.getByText("Ask")).toBeVisible();
  expect(screen.queryByRole("switch")).not.toBeInTheDocument();
});

test("an integration the user cannot see shows the error state", async () => {
  window.history.replaceState(null, "", "/app/customize/integrations/9");
  mockFetch({ "/api/integrations": [makeMemberIntegration()] });
  render(<CustomizeIntegrationPage integrationId={9} />);
  expect(await screen.findByText(copy.loadFailed)).toBeVisible();
});
