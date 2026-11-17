import type { ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import {
  useAgentChatPlugins,
  useAgentPluginPreferences,
} from "@/lib/plugins/hooks";
import {
  mockFetch,
  requestBody,
} from "@/sections/integrations/__tests__/integrationFixtures";
import {
  LINEAR_PLUGIN_ID,
  makeMemberIntegration,
  REPORTS_PLUGIN_ID,
} from "@/sections/plugins/__tests__/memberIntegrationFixtures";

function wrapper({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      {children}
    </SWRConfig>
  );
}

const linear = makeMemberIntegration();
const reports = makeMemberIntegration({
  id: 2,
  name: "Reports API",
  plugins: [
    {
      plugin_id: REPORTS_PLUGIN_ID,
      plugin_name: "Reports",
      scope: "organization",
      owner_email: null,
      installation_policy: "AVAILABLE",
      enabled: true,
    },
  ],
});

afterEach(() => jest.restoreAllMocks());

test("an agent's plugins come from the persona detail", async () => {
  mockFetch({
    "/api/integrations": [linear, reports],
    "/api/persona/8": {
      id: 8,
      plugins: [
        {
          plugin_id: LINEAR_PLUGIN_ID,
          plugin_name: "Linear",
          action_settings: { default: "inherit", actions: {} },
        },
        {
          plugin_id: "skill-plugin",
          plugin_name: "report-writer",
          action_settings: { default: "inherit", actions: {} },
        },
      ],
    },
  });
  const { result } = renderHook(() => useAgentChatPlugins(8), { wrapper });
  await waitFor(() => expect(result.current.pluginIds).not.toBeNull());
  expect(result.current.pluginIds).toEqual([LINEAR_PLUGIN_ID, "skill-plugin"]);
  expect(result.current.plugins.map((plugin) => plugin.name)).toEqual([
    "Linear",
  ]);
});

test("the default agent uses each plugin of the user that holds integrations", async () => {
  mockFetch({ "/api/integrations": [linear, reports] });
  const { result } = renderHook(() => useAgentChatPlugins(0), { wrapper });
  await waitFor(() => expect(result.current.pluginIds).not.toBeNull());
  expect(result.current.pluginIds).toEqual(
    [LINEAR_PLUGIN_ID, REPORTS_PLUGIN_ID].sort()
  );
  expect(result.current.plugins.map((plugin) => plugin.name)).toEqual([
    "Linear",
    "Reports",
  ]);
});

test("the default agent leaves out a plugin the user turned off", async () => {
  const [ref] = reports.plugins;
  if (!ref) throw new Error("Missing fixture plugin");
  mockFetch({
    "/api/integrations": [
      linear,
      { ...reports, plugins: [{ ...ref, enabled: false }] },
    ],
  });
  const { result } = renderHook(() => useAgentChatPlugins(0), { wrapper });
  await waitFor(() => expect(result.current.pluginIds).not.toBeNull());
  expect(result.current.pluginIds).toEqual([LINEAR_PLUGIN_ID]);
  expect(result.current.plugins.map((plugin) => plugin.name)).toEqual([
    "Linear",
  ]);
});

test("turning a plugin off saves disabled_plugin_ids and keeps the built-in tools", async () => {
  const fetchMock = mockFetch({
    "/api/user/assistant/preferences": {
      "8": { disabled_tool_ids: [3], disabled_plugin_ids: ["other"] },
    },
    "PATCH /api/user/assistant/8/preferences": new Response(null),
  });
  const { result } = renderHook(() => useAgentPluginPreferences(true), {
    wrapper,
  });
  await waitFor(() => expect(result.current.loaded).toBe(true));
  expect(result.current.disabledPluginIds(8)).toEqual(["other"]);

  await act(() =>
    result.current.setPluginsDisabled(8, [LINEAR_PLUGIN_ID], true)
  );
  expect(
    requestBody(fetchMock, "PATCH", "/api/user/assistant/8/preferences")
  ).toEqual({
    disabled_tool_ids: [3],
    disabled_plugin_ids: ["other", LINEAR_PLUGIN_ID],
  });
  expect(result.current.disabledPluginIds(8)).toEqual([
    "other",
    LINEAR_PLUGIN_ID,
  ]);
});
