import { PointerEventsCheckLevel } from "@testing-library/user-event";
import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import IntegrationConnectPrompt from "@/sections/plugins/IntegrationConnectPrompt";
import messages from "@/i18n/messages/en.json";
import type { MemberIntegration } from "@/lib/integrations/types";
import { mockFetch, requestBody } from "@tests/setup/integrationTestUtils";
import { makeMemberIntegration } from "@tests/setup/memberIntegrationTestUtils";

const copy = messages.plugins.chat.connectPrompt;
let mockIntegrations: MemberIntegration[] = [];
const mockRefresh = jest.fn(() => Promise.resolve());

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => "/app",
  useSearchParams: () => new URLSearchParams("chatId=chat-1"),
}));
jest.mock("@opal/navigation", () => ({
  ...jest.requireActual<typeof import("@opal/navigation")>("@opal/navigation"),
  loadPage: jest.fn(),
}));
jest.mock("@/lib/integrations/hooks", () => ({
  useAgentChatIntegrations: () => ({
    integrationIds: mockIntegrations.map((integration) => integration.id),
    integrations: mockIntegrations,
    isLoading: false,
    error: undefined,
    refresh: mockRefresh,
  }),
}));

const linear = makeMemberIntegration();
const reports = makeMemberIntegration({
  id: 2,
  name: "Reports API",
  status: {
    state: "needs_reconnect",
    reason: "Your admin changed the sign-in settings",
  },
});
const shared = makeMemberIntegration({
  id: 3,
  name: "Shared app",
  status: { state: "not_set_up", reason: null },
});

function user() {
  return setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
}

beforeEach(() => {
  mockIntegrations = [linear, shared, reports];
});
afterEach(() => {
  jest.restoreAllMocks();
  mockRefresh.mockClear();
});

test("lists the integrations that are on and need sign-in", async () => {
  render(
    <IntegrationConnectPrompt
      agentId={8}
      toolConfiguration={{ ready: true, isIntegrationEnabled: () => true }}
    />
  );
  const trigger = screen.getByRole("button", {
    name: "2 integrations need sign-in",
  });
  await user().click(trigger);
  const dialog = await screen.findByRole("dialog");
  expect(
    within(dialog).getByRole("button", { name: "Connect Linear" })
  ).toBeVisible();
  expect(
    within(dialog).getByRole("button", { name: "Reconnect Reports API" })
  ).toBeVisible();
  expect(
    within(dialog).getByText("Your admin changed the sign-in settings")
  ).toBeVisible();
  expect(within(dialog).queryByText("Shared app")).not.toBeInTheDocument();
  expect(within(dialog).getByText(copy.hint)).toBeVisible();
});

test("skips the integrations that are off in this chat", () => {
  render(
    <IntegrationConnectPrompt
      agentId={8}
      toolConfiguration={{
        ready: true,
        isIntegrationEnabled: (id) => id !== reports.id,
      }}
    />
  );
  expect(
    screen.getByRole("button", { name: "1 integration needs sign-in" })
  ).toBeVisible();
});

test("keeps a Required integration that a stale switch turned off", () => {
  mockIntegrations = [
    {
      ...reports,
      access: { ...reports.access, installation_policy: "REQUIRED" },
    },
  ];
  render(
    <IntegrationConnectPrompt
      agentId={8}
      toolConfiguration={{ ready: true, isIntegrationEnabled: () => false }}
    />
  );
  expect(
    screen.getByRole("button", { name: "1 integration needs sign-in" })
  ).toBeVisible();
});

test("shows nothing when every integration is connected", () => {
  mockIntegrations = [
    makeMemberIntegration({ status: { state: "connected", reason: null } }),
  ];
  render(
    <IntegrationConnectPrompt
      agentId={8}
      toolConfiguration={{ ready: true, isIntegrationEnabled: () => true }}
    />
  );
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

test("reads the statuses again when the user opens it, not on each render", async () => {
  const { rerender } = render(
    <IntegrationConnectPrompt
      agentId={8}
      toolConfiguration={{ ready: true, isIntegrationEnabled: () => true }}
    />
  );
  rerender(
    <IntegrationConnectPrompt
      agentId={8}
      toolConfiguration={{ ready: true, isIntegrationEnabled: () => true }}
    />
  );
  expect(mockRefresh).not.toHaveBeenCalled();
  await user().click(
    screen.getByRole("button", { name: "2 integrations need sign-in" })
  );
  expect(mockRefresh).toHaveBeenCalledTimes(1);
});
