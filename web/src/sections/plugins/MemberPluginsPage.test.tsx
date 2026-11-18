import type { ComponentProps } from "react";
import { render, screen, setupUser, within } from "@tests/setup/test-utils";
import MemberPluginsPage from "@/sections/plugins/MemberPluginsPage";
import type AddIntegrationModal from "@/sections/integrations/AddIntegrationModal";
import messages from "@/i18n/messages/en.json";
import { customFixture } from "@/lib/skills/__fixtures__/picker";
import { mockFetch } from "@tests/setup/integrationTestUtils";
import {
  makeMemberIntegration,
  REPORTS_PLUGIN_ID,
} from "@tests/setup/memberIntegrationTestUtils";

const copy = messages.plugins.member;
const mockPush = jest.fn();
let mockCanManage = false;
const mockModalProps = jest.fn();

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  useRouter: () => ({ push: mockPush, replace: mockPush }),
  usePathname: () => "/app/plugins",
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({
    isGlobalHolder: false,
    isScopedManager: mockCanManage,
  }),
}));
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: { email: "me@example.com" } }),
}));
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ onyx_craft_available: false }),
}));
jest.mock("@/sections/integrations/AddIntegrationModal", () => ({
  __esModule: true,
  default: function MockAddIntegrationModal(
    props: ComponentProps<typeof AddIntegrationModal>
  ) {
    mockModalProps(props);
    return (
      <div role="dialog" aria-label="Add integration">
        <button
          onClick={() =>
            props.onCreated({
              ...jest
                .requireActual<
                  typeof import("@tests/setup/integrationTestUtils")
                >("@tests/setup/integrationTestUtils")
                .makeDetail(),
              plugins: [
                {
                  plugin_id: REPORTS_PLUGIN_ID,
                  plugin_name: "Reports",
                  scope: "personal",
                  owner_email: "me@example.com",
                  installation_policy: null,
                },
              ],
            })
          }
        >
          Create
        </button>
      </div>
    );
  },
}));

const skill = customFixture({
  id: "33333333-3333-4333-8333-333333333333",
  name: "report-writer",
  description: "Draft reports",
  owner: { id: "u1", email: "me@example.com" },
});

function routes() {
  return mockFetch({
    "/api/skills": { builtins: [], customs: [skill] },
    "/api/integrations": [
      makeMemberIntegration(),
      makeMemberIntegration({
        id: 2,
        name: "Reports API",
        description: "Weekly reports",
        status: { state: "connected", reason: null },
        plugins: [
          {
            plugin_id: REPORTS_PLUGIN_ID,
            plugin_name: "Reports",
            scope: "personal",
            owner_email: "me@example.com",
            installation_policy: null,
            enabled: true,
          },
        ],
      }),
    ],
  });
}

beforeEach(() => {
  mockCanManage = false;
  mockPush.mockClear();
  mockModalProps.mockClear();
});
afterEach(() => jest.restoreAllMocks());

test("lists skill and integration plugins by section with the sign-in count", async () => {
  routes();
  render(<MemberPluginsPage />);
  const linear = await screen.findByRole("button", { name: "Open Linear" });
  expect(within(linear).getByText("1 needs sign-in")).toBeInTheDocument();
  expect(screen.getByText(copy.sections.organization)).toBeInTheDocument();
  expect(screen.getByText(copy.sections.mine)).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Open report-writer" })
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Open Reports" })
  ).toBeInTheDocument();
});

test("filters by skills and integrations and searches", async () => {
  routes();
  const user = setupUser();
  render(<MemberPluginsPage />);
  await screen.findByRole("button", { name: "Open Linear" });

  await user.click(
    screen.getByRole("button", { name: copy.filters.skills.label })
  );
  expect(
    screen.getByRole("button", { name: "Open report-writer" })
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Open Linear" })
  ).not.toBeInTheDocument();

  await user.click(
    screen.getByRole("button", { name: copy.filters.integrations.label })
  );
  expect(
    screen.queryByRole("button", { name: "Open report-writer" })
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Open Linear" })).toBeVisible();

  await user.click(
    screen.getByRole("button", { name: copy.filters.all.label })
  );
  await user.type(screen.getByLabelText(copy.search.placeholder), "weekly");
  expect(screen.getByRole("button", { name: "Open Reports" })).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Open Linear" })
  ).not.toBeInTheDocument();
});

test("opens a plugin page", async () => {
  routes();
  render(<MemberPluginsPage />);
  await setupUser().click(
    await screen.findByRole("button", { name: "Open Linear" })
  );
  expect(window.location.pathname).toBe(
    "/app/plugins/11111111-1111-4111-8111-111111111111"
  );
});

test("a member with manage:actions adds a personal integration", async () => {
  mockCanManage = true;
  routes();
  const user = setupUser();
  render(<MemberPluginsPage />);
  await user.click(
    await screen.findByRole("button", { name: copy.addIntegration.label })
  );
  expect(mockModalProps).toHaveBeenCalledWith(
    expect.objectContaining({ canChooseOrganization: false })
  );
  await user.click(screen.getByRole("button", { name: "Create" }));
  expect(window.location.pathname).toBe(`/app/plugins/${REPORTS_PLUGIN_ID}`);
  expect(window.location.search).toBe("?tab=integrations");
});

test("a member without manage:actions cannot add an integration", async () => {
  routes();
  render(<MemberPluginsPage />);
  await screen.findByRole("button", { name: "Open Linear" });
  expect(
    screen.queryByRole("button", { name: copy.addIntegration.label })
  ).not.toBeInTheDocument();
});
