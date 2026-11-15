import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import * as React from "react";
import { act, renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { apiFetch, type ApiFetchInit } from "@/api/client";
import { QUERY_KEYS } from "@/api/query-keys";
import type { AgentPreferences } from "@/api/chat/agentPreferences";
import { useAgentPreferences } from "@/hooks/useAgentPreferences";

jest.mock("@/api/client");
/*
 * The hook reads the live session identity when a queued write finally runs, so the mock needs a
 * `getState` a test can move underneath it.
 */
let mockServerUrl: string | null = "https://example.test";
jest.mock("@/state/session", () => {
  const useSession = (selector: (s: { serverUrl: string | null }) => unknown) =>
    selector({ serverUrl: mockServerUrl });
  useSession.getState = () => ({ serverUrl: mockServerUrl });
  return { useSession };
});
jest.mock("@/hooks/useToast", () => ({ toast: { error: jest.fn() } }));

const apiFetchMock = apiFetch as unknown as Mock<
  (path: string, init?: ApiFetchInit) => Promise<unknown>
>;

const SERVER_URL = "https://example.test";

/*
 * The PATCH invalidates and refetches, so a static mock would answer that refetch with stale data
 * and mask the very races these tests exist to catch.
 */
function fakeServer(
  initial: AgentPreferences,
  {
    patchInFlight = false,
    patchDelaysMs = [],
  }: { patchInFlight?: boolean; patchDelaysMs?: number[] } = {},
) {
  let patchCount = 0;
  let stored: AgentPreferences = initial;
  apiFetchMock.mockImplementation(async (path, init) => {
    if (init?.method === "PATCH") {
      const agentId = path.split("/")[3];
      const { disabled_tool_ids } = init.body as {
        disabled_tool_ids: number[];
      };
      /*
       * Committing a tick late lets a second toggle start before the first lands — the only way
       * to observe the concurrent path the UI actually takes.
       */
      const delay = patchDelaysMs[patchCount++];
      if (delay !== undefined) {
        await new Promise((resolve) => setTimeout(resolve, delay));
      } else if (patchInFlight) {
        await new Promise((resolve) => setTimeout(resolve, 0));
      }
      stored = { ...stored, [agentId]: { disabled_tool_ids } };
      return undefined;
    }
    return stored;
  });
  return {
    disabledFor: (agentId: number) =>
      stored[String(agentId)]?.disabled_tool_ids,
  };
}

function patchCalls() {
  return apiFetchMock.mock.calls.filter(([, init]) => init?.method === "PATCH");
}

function renderPreferences() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const settle = () => waitFor(() => expect(client.isFetching()).toBe(0));
  return {
    client,
    settle,
    ...renderHook(() => useAgentPreferences(), { wrapper }),
  };
}

describe("useAgentPreferences", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    mockServerUrl = SERVER_URL;
  });

  it("reads disabled ids by agent, indexing the string keys the wire sends", async () => {
    fakeServer({ "5": { disabled_tool_ids: [2, 4] } });

    const { result } = renderPreferences();
    await waitFor(() =>
      expect(result.current.disabledToolIdsFor(5)).toEqual([2, 4]),
    );
    expect(result.current.disabledToolIdsFor(9)).toEqual([]);
  });

  it("treats a null body as no preferences", async () => {
    apiFetchMock.mockResolvedValue(null);

    const { result } = renderPreferences();
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    expect(result.current.disabledToolIdsFor(5)).toEqual([]);
  });

  it("adds the tool optimistically and PATCHes the full array", async () => {
    const server = fakeServer({ "5": { disabled_tool_ids: [2] } });

    const { result, client, settle } = renderPreferences();
    await waitFor(() =>
      expect(result.current.disabledToolIdsFor(5)).toEqual([2]),
    );

    await act(async () => {
      await result.current.setToolDisabled(5, 7, true);
    });
    await settle();

    expect(patchCalls()).toEqual([
      [
        "/user/assistant/5/preferences",
        { method: "PATCH", body: { disabled_tool_ids: [2, 7] } },
      ],
    ]);
    expect(server.disabledFor(5)).toEqual([2, 7]);
    expect(
      client.getQueryData<AgentPreferences>(
        QUERY_KEYS.agentPreferences(SERVER_URL),
      ),
    ).toEqual({ "5": { disabled_tool_ids: [2, 7] } });
  });

  it("removes the tool when asked to switch it back on", async () => {
    const server = fakeServer({ "5": { disabled_tool_ids: [2, 7] } });

    const { result, settle } = renderPreferences();
    await waitFor(() =>
      expect(result.current.disabledToolIdsFor(5)).toEqual([2, 7]),
    );

    await act(async () => {
      await result.current.setToolDisabled(5, 7, false);
    });
    await settle();

    expect(server.disabledFor(5)).toEqual([2]);
  });

  it("writes nothing when the tool is already in the state asked for", async () => {
    /*
     * The coupling effect re-asks whenever the source count moves, so asking twice has to be the
     * same as asking once — a flip would invert the record it just wrote.
     */
    fakeServer({ "5": { disabled_tool_ids: [7] } });

    const { result, settle } = renderPreferences();
    await waitFor(() =>
      expect(result.current.disabledToolIdsFor(5)).toEqual([7]),
    );

    await act(async () => {
      await result.current.setToolDisabled(5, 7, true);
    });
    await settle();

    expect(patchCalls()).toEqual([]);
  });

  it("reports the record as unloaded until the GET lands", async () => {
    fakeServer({ "5": { disabled_tool_ids: [7] } });

    const { result } = renderPreferences();
    expect(result.current.isLoaded).toBe(false);
    await waitFor(() => expect(result.current.isLoaded).toBe(true));
  });

  it("leaves other agents' preferences untouched", async () => {
    const server = fakeServer({
      "5": { disabled_tool_ids: [2] },
      "6": { disabled_tool_ids: [9] },
    });

    const { result, settle } = renderPreferences();
    await waitFor(() =>
      expect(result.current.disabledToolIdsFor(6)).toEqual([9]),
    );

    await act(async () => {
      await result.current.setToolDisabled(5, 7, true);
    });
    await settle();

    expect(server.disabledFor(6)).toEqual([9]);
  });

  it("rolls the cache back when the PATCH fails", async () => {
    fakeServer({ "5": { disabled_tool_ids: [2] } });

    const { result, client, settle } = renderPreferences();
    await waitFor(() =>
      expect(result.current.disabledToolIdsFor(5)).toEqual([2]),
    );

    apiFetchMock.mockRejectedValue(new Error("nope"));
    await act(async () => {
      await result.current.setToolDisabled(5, 7, true);
    });
    await settle();

    expect(
      client.getQueryData<AgentPreferences>(
        QUERY_KEYS.agentPreferences(SERVER_URL),
      ),
    ).toEqual({ "5": { disabled_tool_ids: [2] } });
  });

  it("loads the record before PATCHing so a pre-load tap can't wipe other clients' choices", async () => {
    const server = fakeServer({ "5": { disabled_tool_ids: [2, 4] } });

    // No waitFor: the tap lands while the initial GET is still in flight, so the cache is empty.
    const { result, settle } = renderPreferences();
    await act(async () => {
      await result.current.setToolDisabled(5, 7, true);
    });
    await settle();

    expect(server.disabledFor(5)).toEqual([2, 4, 7]);
  });

  it("does not PATCH at all when the record cannot be loaded", async () => {
    apiFetchMock.mockRejectedValue(new Error("offline"));

    const { result } = renderPreferences();
    await act(async () => {
      await result.current.setToolDisabled(5, 7, true);
    });

    expect(patchCalls()).toEqual([]);
  });

  it("composes two in-flight writes rather than dropping one", async () => {
    const server = fakeServer(
      { "5": { disabled_tool_ids: [] } },
      { patchInFlight: true },
    );

    const { result, settle } = renderPreferences();
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());

    await act(async () => {
      await Promise.all([
        result.current.setToolDisabled(5, 1, true),
        result.current.setToolDisabled(5, 2, true),
      ]);
    });
    await settle();

    expect(server.disabledFor(5)).toEqual([1, 2]);
  });

  it("keeps both writes when the first PATCH lands after the second", async () => {
    const server = fakeServer(
      { "5": { disabled_tool_ids: [] } },
      { patchDelaysMs: [40, 0] },
    );

    const { result, settle } = renderPreferences();
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());

    await act(async () => {
      await Promise.all([
        result.current.setToolDisabled(5, 1, true),
        result.current.setToolDisabled(5, 2, true),
      ]);
    });
    await settle();

    expect(server.disabledFor(5)).toEqual([1, 2]);
  });

  it("drops a write when the session it was made under is gone", async () => {
    const server = fakeServer(
      { "5": { disabled_tool_ids: [] } },
      { patchInFlight: true },
    );

    const { result, settle } = renderPreferences();
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());

    await act(async () => {
      await result.current.setToolDisabled(5, 1, true);
    });
    await settle();
    expect(server.disabledFor(5)).toEqual([1]);

    await act(async () => {
      const pending = result.current.setToolDisabled(5, 2, true);
      mockServerUrl = "https://other.test";
      await pending;
    });

    expect(server.disabledFor(5)).toEqual([1]);
  });

  it("composes consecutive writes instead of racing on a stale array", async () => {
    const server = fakeServer({ "5": { disabled_tool_ids: [] } });

    const { result, settle } = renderPreferences();
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());

    await act(async () => {
      await result.current.setToolDisabled(5, 1, true);
      await result.current.setToolDisabled(5, 2, true);
    });
    await settle();

    expect(server.disabledFor(5)).toEqual([1, 2]);
  });
});
