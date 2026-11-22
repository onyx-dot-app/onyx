import { PointerEventsCheckLevel } from "@testing-library/user-event";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import ChatIntegrationsPopover from "@/sections/plugins/ChatIntegrationsPopover";
import messages from "@/i18n/messages/en.json";
import type { AgentChatIntegrations } from "@/lib/integrations/hooks";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";
import {
  makeAccess,
  makeMemberIntegration,
} from "@tests/setup/memberIntegrationTestUtils";

const copy = messages.plugins.chat.popover;

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => "/app",
}));
jest.mock("@/lib/navigation/hooks", () => ({
  useAppPosition: () => ({ chat: () => "chat-1", project: () => null }),
}));

function handle(disabled: number[] = []): ToolConfigurationHandle {
  return {
    stateOf: () => null,
    setToolState: jest.fn(),
    toggleToolState: jest.fn(),
    clearPreferredTool: jest.fn(),
    preferredToolId: null,
    preferredAction: null,
    disabledToolIds: [],
    isIntegrationEnabled: (id) => !disabled.includes(id),
    setIntegrationEnabled: jest.fn(),
    allowed: null,
    ready: true,
    optionsLoaded: true,
    filters: {
      selectedSources: null,
      documentSets: [],
      tags: [],
      timeRange: null,
    },
    setFilters: jest.fn(),
    handOffTo: jest.fn(),
    handOffToNewChatWith: jest.fn(),
  };
}

const linear = makeMemberIntegration({
  status: { state: "connected", reason: null },
  access: makeAccess({ state: "on" }),
});
const reports = makeMemberIntegration({ id: 2, name: "Reports API" });

const catalog: AgentChatIntegrations = {
  integrationIds: [1, 2],
  integrations: [linear, reports],
  isLoading: false,
  error: undefined,
  refresh: jest.fn(),
};

function user() {
  return setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
}

test("an integration that needs sign-in keeps its switch, and Connect turns it on", async () => {
  const configuration = handle([2]);
  const onConnect = jest.fn();
  const u = user();
  render(
    <ChatIntegrationsPopover
      agentId={8}
      toolConfiguration={configuration}
      catalog={catalog}
      onConnect={onConnect}
      onBrowse={jest.fn()}
    />
  );
  await u.click(screen.getByRole("button", { name: copy.trigger.label }));
  expect(
    await screen.findByRole("switch", {
      name: "Use Reports API with this agent",
    })
  ).not.toBeChecked();
  await u.click(
    screen.getByRole("button", {
      name: messages.plugins.member.connection.connect.label,
    })
  );
  expect(configuration.setIntegrationEnabled).toHaveBeenCalledWith([2], true);
  expect(onConnect).toHaveBeenCalledWith(reports);
});

test("a Required integration shows on and its switch is locked", async () => {
  const configuration = handle([1]);
  const u = user();
  render(
    <ChatIntegrationsPopover
      agentId={8}
      toolConfiguration={configuration}
      catalog={{
        ...catalog,
        integrations: [
          {
            ...linear,
            access: makeAccess({
              state: "on",
              installation_policy: "REQUIRED",
            }),
          },
        ],
      }}
      onConnect={jest.fn()}
      onBrowse={jest.fn()}
    />
  );
  await u.click(screen.getByRole("button", { name: copy.trigger.label }));
  const toggle = await screen.findByRole("switch", {
    name: "Use Linear with this agent",
  });
  expect(toggle).toBeChecked();
  expect(toggle).toHaveAttribute("aria-disabled", "true");
  expect(
    screen.getByText(messages.integrations.memberState.switch.required)
  ).toBeVisible();
});

test("says when the agent has no integrations", async () => {
  const u = user();
  render(
    <ChatIntegrationsPopover
      agentId={8}
      toolConfiguration={handle()}
      catalog={{ ...catalog, integrationIds: [], integrations: [] }}
      onConnect={jest.fn()}
      onBrowse={jest.fn()}
    />
  );
  await u.click(screen.getByRole("button", { name: copy.trigger.label }));
  expect(await screen.findByText(copy.empty)).toBeVisible();
});
