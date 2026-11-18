import type { ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import {
  useAgentChatPlugins,
  useAgentPluginPreferences,
} from "@/lib/plugins/hooks";
import { mockFetch, requestBody } from "@tests/setup/integrationTestUtils";
import {
  LINEAR_PLUGIN_ID,
  makeMemberIntegration,
  REPORTS_PLUGIN_ID,
} from "@tests/setup/memberIntegrationTestUtils";

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

test("an agent's plugins come from the server list", async () => {
  mockFetch({
    "/api/integrations": [linear, reports],
    "/api/plugins/agents/8": ["skill-plugin", LINEAR_PLUGIN_ID],
  });
  const { result } = renderHook(() => useAgentChatPlugins(8), { wrapper });
  await waitFor(() => expect(result.current.plugins).toHaveLength(1));
  expect(result.current.pluginIds).toEqual(
    [LINEAR_PLUGIN_ID, "skill-plugin"].sort()
  );
  expect(result.current.plugins.map((plugin) => plugin.name)).toEqual([
    "Linear",
  ]);
});

test("the default agent runs the plugins the server lists", async () => {
  const [ref] = reports.plugins;
  if (!ref) throw new Error("Missing fixture plugin");
  mockFetch({
    "/api/integrations": [
      linear,
      { ...reports, plugins: [{ ...ref, enabled: false }] },
    ],
    "/api/plugins/agents/0": [REPORTS_PLUGIN_ID],
  });
  const { result } = renderHook(() => useAgentChatPlugins(0), { wrapper });
  await waitFor(() => expect(result.current.plugins).toHaveLength(1));
  expect(result.current.pluginIds).toEqual([REPORTS_PLUGIN_ID]);
  expect(result.current.plugins.map((plugin) => plugin.name)).toEqual([
    "Reports",
  ]);
});

test("turning a plugin off sends only disabled_plugin_ids", async () => {
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
  ).toEqual({ disabled_plugin_ids: ["other", LINEAR_PLUGIN_ID] });
  expect(result.current.disabledPluginIds(8)).toEqual([
    "other",
    LINEAR_PLUGIN_ID,
  ]);
});

test("a failed plugin list read leaves the agent's plugins unknown", async () => {
  mockFetch({
    "/api/integrations": [linear, reports],
    "/api/plugins/agents/8": new Response(JSON.stringify({ detail: "down" }), {
      status: 500,
    }),
  });
  const { result } = renderHook(() => useAgentChatPlugins(8), { wrapper });
  await waitFor(() => expect(result.current.error).toBeDefined());
  expect(result.current.pluginIds).toBeNull();
  expect(result.current.plugins).toEqual([]);
});

test("refresh reads the integrations again and not the plugin list", async () => {
  const fetchMock = mockFetch({
    "/api/integrations": [linear],
    "/api/plugins/agents/8": [LINEAR_PLUGIN_ID],
  });
  const { result } = renderHook(() => useAgentChatPlugins(8), { wrapper });
  await waitFor(() => expect(result.current.plugins).toHaveLength(1));
  const reads = (url: string) =>
    fetchMock.mock.calls.filter(([input]) => String(input) === url).length;
  const before = reads("/api/plugins/agents/8");

  await act(() => result.current.refresh());
  expect(reads("/api/integrations")).toBe(2);
  expect(reads("/api/plugins/agents/8")).toBe(before);
});

test("a failed preferences read is not loaded and a switch fails", async () => {
  const fetchMock = mockFetch({
    "/api/user/assistant/preferences": new Response(
      JSON.stringify({ detail: "down" }),
      { status: 500 }
    ),
  });
  const { result } = renderHook(() => useAgentPluginPreferences(true), {
    wrapper,
  });
  await waitFor(() => expect(result.current.error).toBeDefined());
  expect(result.current.loaded).toBe(false);
  expect(result.current.disabledPluginIds(8)).toBeNull();
  await expect(
    result.current.setPluginsDisabled(8, [LINEAR_PLUGIN_ID], true)
  ).rejects.toThrow();
  expect(
    fetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")
  ).toBe(false);
});
