import type { ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import {
  useAgentChatIntegrations,
  useAgentIntegrationPreferences,
} from "@/lib/integrations/hooks";
import { mockFetch, requestBody } from "@tests/setup/integrationTestUtils";
import { makeMemberIntegration } from "@tests/setup/memberIntegrationTestUtils";

function wrapper({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      {children}
    </SWRConfig>
  );
}

const linear = makeMemberIntegration();
const reports = makeMemberIntegration({ id: 2, name: "Reports API" });

afterEach(() => jest.restoreAllMocks());

test("an agent's integrations come from the server list", async () => {
  mockFetch({
    "/api/integrations": [reports, linear],
    "/api/integrations/agents/8": [2, 1, 9],
  });
  const { result } = renderHook(() => useAgentChatIntegrations(8), {
    wrapper,
  });
  await waitFor(() => expect(result.current.integrations).toHaveLength(2));
  expect(result.current.integrationIds).toEqual([1, 2, 9]);
  expect(result.current.integrations.map((entry) => entry.name)).toEqual([
    "Linear",
    "Reports API",
  ]);
});

test("turning an integration off sends only disabled_integration_ids", async () => {
  const fetchMock = mockFetch({
    "/api/user/assistant/preferences": {
      "8": { disabled_tool_ids: [3], disabled_integration_ids: [5] },
    },
    "PATCH /api/user/assistant/8/preferences": new Response(null),
  });
  const { result } = renderHook(() => useAgentIntegrationPreferences(true), {
    wrapper,
  });
  await waitFor(() => expect(result.current.loaded).toBe(true));
  expect(result.current.disabledIntegrationIds(8)).toEqual([5]);

  await act(() => result.current.setIntegrationsDisabled(8, [1], true));
  expect(
    requestBody(fetchMock, "PATCH", "/api/user/assistant/8/preferences")
  ).toEqual({ disabled_integration_ids: [5, 1] });
  expect(result.current.disabledIntegrationIds(8)).toEqual([5, 1]);
});

test("a failed list read leaves the agent's integrations unknown", async () => {
  mockFetch({
    "/api/integrations": [linear, reports],
    "/api/integrations/agents/8": new Response(
      JSON.stringify({ detail: "down" }),
      {
        status: 500,
      }
    ),
  });
  const { result } = renderHook(() => useAgentChatIntegrations(8), {
    wrapper,
  });
  await waitFor(() => expect(result.current.error).toBeDefined());
  expect(result.current.integrationIds).toBeNull();
  expect(result.current.integrations).toEqual([]);
});

test("refresh reads the agent's integrations again", async () => {
  // The user turns on Reports API in another tab: the default agent now
  // uses it.
  let agentIds = [1];
  mockFetch({
    "/api/integrations": [linear, reports],
    "/api/integrations/agents/8": () => agentIds,
  });
  const { result } = renderHook(() => useAgentChatIntegrations(8), {
    wrapper,
  });
  await waitFor(() => expect(result.current.integrations).toHaveLength(1));

  agentIds = [1, 2];
  await act(() => result.current.refresh());
  expect(result.current.integrations.map((entry) => entry.name)).toEqual([
    "Linear",
    "Reports API",
  ]);
});

test("a failed preferences read is not loaded and a switch fails", async () => {
  const fetchMock = mockFetch({
    "/api/user/assistant/preferences": new Response(
      JSON.stringify({ detail: "down" }),
      { status: 500 }
    ),
  });
  const { result } = renderHook(() => useAgentIntegrationPreferences(true), {
    wrapper,
  });
  await waitFor(() => expect(result.current.error).toBeDefined());
  expect(result.current.loaded).toBe(false);
  expect(result.current.disabledIntegrationIds(8)).toBeNull();
  await expect(
    result.current.setIntegrationsDisabled(8, [1], true)
  ).rejects.toThrow();
  expect(
    fetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")
  ).toBe(false);
});

test("a failed refresh leaves the agent's integrations unknown", async () => {
  let fail = false;
  mockFetch({
    "/api/integrations": [linear],
    "/api/integrations/agents/8": () =>
      fail ? new Response(null, { status: 500 }) : [1],
  });
  const { result } = renderHook(() => useAgentChatIntegrations(8), {
    wrapper,
  });
  await waitFor(() => expect(result.current.integrationIds).toEqual([1]));

  fail = true;
  await act(() => result.current.refresh());
  await waitFor(() => expect(result.current.integrationIds).toBeNull());
});

test("a failed write is read back before the next write is built", async () => {
  const patches: unknown[] = [];
  const fetchMock = mockFetch({
    "/api/user/assistant/preferences": {
      "8": { disabled_tool_ids: [], disabled_integration_ids: [5] },
    },
    "PATCH /api/user/assistant/8/preferences": (init?: RequestInit) => {
      patches.push(JSON.parse(String(init?.body)));
      return new Response(null, { status: patches.length === 1 ? 500 : 200 });
    },
  });
  const { result } = renderHook(() => useAgentIntegrationPreferences(true), {
    wrapper,
  });
  await waitFor(() => expect(result.current.loaded).toBe(true));

  await act(async () => {
    const first = result.current.setIntegrationsDisabled(8, [1], true);
    const second = result.current.setIntegrationsDisabled(8, [2], true);
    await expect(first).rejects.toThrow("HTTP 500");
    await second;
  });

  // The second body starts from the saved list, not from the failed change.
  expect(patches).toEqual([
    { disabled_integration_ids: [5, 1] },
    { disabled_integration_ids: [5, 2] },
  ]);
  expect(fetchMock).toHaveBeenCalled();
});

test("a lost write is read back before the next write is built", async () => {
  const patches: unknown[] = [];
  mockFetch({
    "/api/user/assistant/preferences": {
      "8": { disabled_tool_ids: [], disabled_integration_ids: [5] },
    },
    "PATCH /api/user/assistant/8/preferences": (init?: RequestInit) => {
      patches.push(JSON.parse(String(init?.body)));
      if (patches.length === 1) throw new TypeError("Failed to fetch");
      return new Response(null);
    },
  });
  const { result } = renderHook(() => useAgentIntegrationPreferences(true), {
    wrapper,
  });
  await waitFor(() => expect(result.current.loaded).toBe(true));

  await act(async () => {
    const first = result.current.setIntegrationsDisabled(8, [1], true);
    const second = result.current.setIntegrationsDisabled(8, [2], true);
    await expect(first).rejects.toThrow("Failed to fetch");
    await second;
  });

  expect(patches).toEqual([
    { disabled_integration_ids: [5, 1] },
    { disabled_integration_ids: [5, 2] },
  ]);
});
