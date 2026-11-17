import { PointerEventsCheckLevel } from "@testing-library/user-event";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import ChatPluginsPopover from "@/sections/plugins/ChatPluginsPopover";
import messages from "@/i18n/messages/en.json";
import type { AgentChatPlugins } from "@/lib/plugins/hooks";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";
import {
  LINEAR_PLUGIN_ID,
  makeMemberIntegration,
  REPORTS_PLUGIN_ID,
} from "@/sections/plugins/__tests__/memberIntegrationFixtures";

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

function handle(disabled: string[] = []): ToolConfigurationHandle {
  return {
    stateOf: () => null,
    setToolState: jest.fn(),
    toggleToolState: jest.fn(),
    clearPreferredTool: jest.fn(),
    preferredToolId: null,
    preferredAction: null,
    disabledToolIds: [],
    isPluginEnabled: (id) => !disabled.includes(id),
    setPluginEnabled: jest.fn(),
    allowed: null,
    ready: true,
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

const catalog: AgentChatPlugins = {
  pluginIds: [LINEAR_PLUGIN_ID, REPORTS_PLUGIN_ID],
  plugins: [
    {
      pluginId: LINEAR_PLUGIN_ID,
      name: "Linear",
      integrations: [
        makeMemberIntegration({
          status: {
            state: "connected",
            reason: null,
            moving_credentials: false,
          },
        }),
      ],
    },
    {
      pluginId: REPORTS_PLUGIN_ID,
      name: "Reports",
      integrations: [makeMemberIntegration({ id: 2, name: "Reports API" })],
    },
  ],
  isLoading: false,
  error: undefined,
  refresh: jest.fn(),
};

function user() {
  return setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
}

test("switches the agent's plugins and offers Connect for one that needs sign-in", async () => {
  const configuration = handle([LINEAR_PLUGIN_ID]);
  const onConnect = jest.fn();
  const u = user();
  render(
    <ChatPluginsPopover
      agentId={8}
      toolConfiguration={configuration}
      catalog={catalog}
      onConnect={onConnect}
      onBrowse={jest.fn()}
    />
  );
  await u.click(screen.getByRole("button", { name: copy.trigger }));
  const toggle = await screen.findByRole("switch", {
    name: "Use Linear in this chat",
  });
  expect(toggle).not.toBeChecked();
  await u.click(toggle);
  expect(configuration.setPluginEnabled).toHaveBeenCalledWith(
    [LINEAR_PLUGIN_ID],
    true
  );

  await u.click(screen.getByRole("button", { name: copy.connect }));
  expect(onConnect).toHaveBeenCalledWith(catalog.plugins[1]);
});

test("says when the agent has no plugins with integrations", async () => {
  const u = user();
  render(
    <ChatPluginsPopover
      agentId={8}
      toolConfiguration={handle()}
      catalog={{ ...catalog, pluginIds: [], plugins: [] }}
      onConnect={jest.fn()}
      onBrowse={jest.fn()}
    />
  );
  await u.click(screen.getByRole("button", { name: copy.trigger }));
  expect(await screen.findByText(copy.empty)).toBeVisible();
});
