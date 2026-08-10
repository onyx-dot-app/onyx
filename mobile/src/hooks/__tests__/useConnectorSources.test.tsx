import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import * as React from "react";
import { renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { apiFetch, type ApiFetchInit } from "@/api/client";
import { useWorkspaceSettings } from "@/api/settings";
import { useConnectorSources } from "@/hooks/useConnectorSources";

jest.mock("@/api/client");
jest.mock("@/api/settings", () => ({ useWorkspaceSettings: jest.fn() }));
jest.mock("@/state/session", () => ({
  useSession: (selector: (s: { serverUrl: string | null }) => unknown) =>
    selector({ serverUrl: "https://example.test" }),
}));

const apiFetchMock = apiFetch as unknown as Mock<
  (path: string, init?: ApiFetchInit) => Promise<unknown>
>;
const settingsMock = useWorkspaceSettings as unknown as Mock<() => unknown>;

// Only the fields the hook reads; `isPending` is the flag under test here.
function mockSettings({
  vectorDb = true,
  isPending = false,
}: { vectorDb?: boolean; isPending?: boolean } = {}) {
  settingsMock.mockReturnValue({
    isPending,
    settings: {
      disable_default_assistant: false,
      user_file_max_upload_size_mb: null,
      deep_research_enabled: true,
      vector_db_enabled: vectorDb,
    },
  });
}

function connectorCalls(): number {
  return apiFetchMock.mock.calls.filter(
    ([path]) => path === "/manage/connector-status",
  ).length;
}

function renderSources() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useConnectorSources(), { wrapper });
}

describe("useConnectorSources", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    apiFetchMock.mockImplementation((path: string) => {
      if (path === "/manage/connector-status") {
        return Promise.resolve([
          { has_successful_run: true, source: "notion", status: "ACTIVE" },
        ]);
      }
      return Promise.resolve([]);
    });
  });

  it("asks for the connector list once the vector DB is confirmed", async () => {
    mockSettings({ vectorDb: true });

    const { result } = renderSources();

    await waitFor(() => expect(result.current.sources).toEqual(["notion"]));
    expect(connectorCalls()).toBe(1);
  });

  it("never asks for it when the deployment runs without a vector DB", async () => {
    mockSettings({ vectorDb: false });

    const { result } = renderSources();

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(connectorCalls()).toBe(0);
  });

  it("waits for the setting rather than guessing at it", async () => {
    /*
     * The whole `/manage` router answers 501 without a vector DB, and the retry doubles it — so a
     * guess here costs those deployments two failed requests on every launch.
     */
    mockSettings({ isPending: true });

    renderSources();

    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    expect(connectorCalls()).toBe(0);
  });

  it("falls back to asking when the settings call itself failed", async () => {
    // Not pending and not disabled: a settings outage must not empty the picker for everyone.
    mockSettings({ vectorDb: true, isPending: false });

    const { result } = renderSources();

    await waitFor(() => expect(result.current.sources).toEqual(["notion"]));
  });

  it("still offers federated connectors without a vector DB", async () => {
    // Queried live rather than indexed, so they don't depend on the vector DB at all.
    mockSettings({ vectorDb: false });
    apiFetchMock.mockImplementation((path: string) => {
      if (path === "/federated") {
        return Promise.resolve([
          { id: 1, source: "federated_slack", name: "" },
        ]);
      }
      return Promise.resolve([]);
    });

    const { result } = renderSources();

    await waitFor(() =>
      expect(result.current.sources).toEqual(["federated_slack"]),
    );
    expect(connectorCalls()).toBe(0);
  });
});
